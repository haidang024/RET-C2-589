"""RankingNode — Step 3: Aggregate scores, apply hard gates, produce RankedShortlistReport."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_PII_REDACT_PATTERN = re.compile(
    r"\b(name|氏名|address|住所|date_of_birth|生年月日|phone|email|マイナンバー)\b",
    re.IGNORECASE,
)


def _build_compliance_log_entry(candidate: dict[str, Any], rank: int) -> dict[str, Any]:
    """Build a PII-redacted compliance log entry for HR audit trail."""
    return {
        "rank": rank,
        "candidate_id": candidate.get("candidate_id", ""),
        "pass_mandatory": candidate.get("pass_mandatory", False),
        "aggregate_score": candidate.get("aggregate_score", 0.0),
        "shift_overlap_pct": candidate.get("shift_overlap_pct", 0.0),
        "certification_flags": candidate.get("certification_flags", {}),
        "ikusei_shurou_eligible": candidate.get("ikusei_shurou_eligible", False),
        "ikusei_shurou_interim": candidate.get("ikusei_shurou_interim", True),
        "jlpt_match": candidate.get("jlpt_match", False),
        "mandatory_gates": candidate.get("mandatory_gates", {}),
    }


class RankingNode(FunctionNode):
    """Step 3: Rank scored candidates; produce RankedShortlistReport.

    Hard-gate logic: any candidate failing a mandatory criterion is excluded
    from the ranked output regardless of aggregate score.
    PII-redacted compliance log emitted via emit_trace_event for HR audit.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.config: dict[str, Any] = dict(config or {})
        self._shortlist_size = int(self.config.get("shortlist_size", 3))

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3/S-4: Verify ranked_shortlist_report contains no raw PII.

        Scans the serialized report string for known PII field names.
        Any PII fields present in the report trigger a SecurityViolationError.
        """
        report = result.get("ranked_shortlist_report")
        if report is None:
            return result

        import json as _json

        report_str = _json.dumps(report, ensure_ascii=False)

        # Check for raw PII field names — values should already be [REDACTED]
        for pii_field in ('"name"', '"address"', '"date_of_birth"', '"email"', '"phone"'):
            if pii_field in report_str:
                field_name = pii_field.strip('"')
                # Verify value is redacted (not raw data)
                import re as _re

                pattern = rf'"{field_name}"\s*:\s*"(?!\[REDACTED\])'
                if _re.search(pattern, report_str):
                    raise SecurityViolationError(
                        f"Unredacted PII field '{field_name}' detected in ranked_shortlist_report"
                    )
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        scored_resumes = state.get("scored_resumes", [])
        job_id = str(state.get("job_id", "unknown"))

        if not isinstance(scored_resumes, list):
            emit_trace_event(
                "RankingNode_empty_input",
                {"job_id": job_id, "reason": "scored_resumes is not a list"},
                state,
            )
            return {
                "ranked_shortlist_report": {
                    "job_id": job_id,
                    "ranked_list": [],
                    "shortlist_top3": [],
                    "pii_redacted_compliance_log": [],
                    "ranking_summary": {"total": 0, "passed_gates": 0, "excluded": 0},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                "status": AgentStatus.SUCCESS.value,
            }

        # Hard-gate filtering: exclude candidates failing any mandatory criterion
        passed: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []

        for candidate in scored_resumes:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("pass_mandatory", False):
                passed.append(candidate)
            else:
                excluded.append(candidate)

        # Sort passed candidates by aggregate_score descending
        passed_sorted = sorted(
            passed,
            key=lambda c: float(c.get("aggregate_score", 0.0)),
            reverse=True,
        )

        # Build ranked list with per-criterion breakdown (PII-redacted)
        ranked_list: list[dict[str, Any]] = []
        compliance_log: list[dict[str, Any]] = []

        for rank_idx, candidate in enumerate(passed_sorted, start=1):
            ranked_entry = _build_compliance_log_entry(candidate, rank_idx)
            ranked_list.append(ranked_entry)
            compliance_log.append(ranked_entry)

            emit_trace_event(
                "RankingNode_candidate_ranked",
                {
                    "rank": rank_idx,
                    "candidate_id": candidate.get("candidate_id", ""),
                    "aggregate_score": candidate.get("aggregate_score", 0.0),
                    "pass_mandatory": True,
                },
                state,
            )

        # Log excluded candidates (hard-gate failures) for compliance audit
        for candidate in excluded:
            emit_trace_event(
                "RankingNode_candidate_excluded",
                {
                    "candidate_id": candidate.get("candidate_id", ""),
                    "failed_gates": [
                        gate for gate, passed_flag in candidate.get("mandatory_gates", {}).items() if not passed_flag
                    ],
                },
                state,
            )

        shortlist = ranked_list[: self._shortlist_size]

        ranking_summary = {
            "total": len(scored_resumes),
            "passed_gates": len(passed),
            "excluded": len(excluded),
            "shortlist_size": len(shortlist),
        }

        ranked_shortlist_report = {
            "job_id": job_id,
            "ranked_list": ranked_list,
            "shortlist_top3": shortlist,
            "pii_redacted_compliance_log": compliance_log,
            "ranking_summary": ranking_summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        emit_trace_event(
            "RankingNode_ranking_complete",
            {
                "job_id": job_id,
                "total": len(scored_resumes),
                "passed_gates": len(passed),
                "excluded": len(excluded),
                "shortlist_count": len(shortlist),
            },
            state,
        )

        return {
            "ranked_shortlist_report": ranked_shortlist_report,
            "status": AgentStatus.SUCCESS.value,
        }
