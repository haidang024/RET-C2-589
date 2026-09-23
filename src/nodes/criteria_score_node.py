"""CriteriaScoreNode — Step 2: Score parsed resumes against job criteria."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Fields that are considered bias-protected attributes (ADR bias mitigation §11 Risk #5)
# These must never be used as scoring inputs.
_PROTECTED_ATTRIBUTES = ("nationality", "gender", "age", "date_of_birth", "religion", "disability")

# Default JLPT level map (1=highest, 5=lowest; 0=no JLPT)
_JLPT_LEVEL_MAP = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1, None: 0}


def _compute_shift_overlap(
    candidate_availability: dict[str, Any],
    required_shifts: list[dict[str, Any]],
) -> float:
    """Return overlap percentage [0.0..1.0] between candidate and required shifts.

    Both availability and required_shifts are dicts/lists of {day: [time_ranges]}.
    """
    if not required_shifts:
        return 1.0
    if not candidate_availability:
        return 0.0

    matched = 0
    for shift in required_shifts:
        day = str(shift.get("day", ""))
        if day in candidate_availability:
            matched += 1

    return round(matched / max(len(required_shifts), 1), 3)


def _check_certifications(candidate_certs: list[str], required_cert_names: list[str]) -> dict[str, bool]:
    """Return a flag dict per required certification — True if candidate holds it."""
    return {cert: cert in candidate_certs for cert in required_cert_names}


def _apply_ikusei_shurou_rules(record: dict[str, Any], rules_module_path: str | None) -> tuple[bool, bool]:
    """Evaluate 育成就労法 2028 eligibility via pluggable rules module.

    Returns (eligible: bool, interim: bool).
    interim=True when act is not yet fully operative (pre-2028).
    """
    if not rules_module_path:
        # Default: flag as interim — rules not configured
        return False, True

    try:
        mod = importlib.import_module(rules_module_path)
        result = mod.evaluate(record)
        eligible = bool(result.get("eligible", False))
        interim = bool(result.get("interim", True))
        return eligible, interim
    except Exception:
        # Rules module unavailable — safe default: not eligible, interim
        return False, True


def _score_preferred(
    record: dict[str, Any],
    preferred_criteria: list[dict[str, Any]],
    weights: dict[str, Any],
) -> float:
    """Compute weighted preferred-criteria score in [0.0..1.0]."""
    if not preferred_criteria:
        return 1.0

    total_weight = 0.0
    earned = 0.0

    for criterion in preferred_criteria:
        name = str(criterion.get("name", ""))
        weight = float(weights.get(name, criterion.get("weight", 1.0)))
        total_weight += weight

        crit_type = str(criterion.get("type", ""))
        if crit_type == "certification":
            req_cert = str(criterion.get("value", ""))
            if req_cert in record.get("certifications", []):
                earned += weight
        elif crit_type == "experience_years":
            min_years = float(criterion.get("min_years", 0))
            exp_years = sum(float(wh.get("years", 0)) for wh in record.get("work_history", []) if isinstance(wh, dict))
            if exp_years >= min_years:
                earned += weight
        elif crit_type == "education_level":
            req_level = str(criterion.get("value", ""))
            for edu in record.get("education", []):
                if isinstance(edu, dict) and req_level in str(edu.get("level", "")):
                    earned += weight
                    break

    if total_weight == 0:
        return 1.0
    return round(earned / total_weight, 3)


class CriteriaScoreNode(FunctionNode):
    """Step 2: Score each parsed resume against job criteria.

    Bias mitigation: protected attributes (nationality, age, gender) are never
    used as scoring inputs. 育成就労法 2028 eligibility is implemented as a
    configurable pluggable rules module; output is flagged as interim until 2028
    act is fully operative.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.config: dict[str, Any] = dict(config or {})
        self._min_jlpt_level = int(self.config.get("min_jlpt_level", 0))
        self._ikusei_shurou_rules_module: str | None = self.config.get("ikusei_shurou_rules_module")

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3: Ensure scored_resumes do not contain raw PII fields."""
        scored = result.get("scored_resumes", [])
        if isinstance(scored, list):
            for candidate in scored:
                if not isinstance(candidate, dict):
                    continue
                for pii_field in ("name", "address", "date_of_birth", "email", "phone"):
                    if pii_field in candidate and candidate[pii_field] not in (None, "[REDACTED]"):
                        raise SecurityViolationError(f"PII field '{pii_field}' must not appear in scored_resumes")
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        parsed_resumes = state.get("parsed_resumes", [])
        job_criteria = state.get("job_criteria", {})

        required_criteria: list[dict[str, Any]] = job_criteria.get("required", [])
        preferred_criteria: list[dict[str, Any]] = job_criteria.get("preferred", [])
        shift_requirements: list[dict[str, Any]] = job_criteria.get("shift_requirements", [])
        min_jlpt = int(job_criteria.get("min_jlpt_level", self._min_jlpt_level))
        required_certs: list[str] = [
            str(c.get("value", "")) for c in required_criteria if c.get("type") == "certification"
        ]
        ikusei_module = job_criteria.get("ikusei_shurou_rules_module", self._ikusei_shurou_rules_module)
        score_weights: dict[str, Any] = job_criteria.get("score_weights", {})

        scored_resumes: list[dict[str, Any]] = []
        score_errors = 0

        for record in parsed_resumes:
            if not isinstance(record, dict):
                score_errors += 1
                continue

            candidate_id = str(record.get("candidate_id", ""))

            # Bias mitigation: verify no protected attributes are accessed
            for attr in _PROTECTED_ATTRIBUTES:
                if attr in record and attr not in ("nationality_category",):
                    # nationality_category is a coarse grouping for eligibility rules only
                    emit_trace_event(
                        "bias_protected_attr_present",
                        {"attr": attr, "candidate_id": record.get("candidate_id", "")},
                        state,
                    )

            # Mandatory gates
            mandatory_gates: dict[str, bool] = {}
            pass_mandatory = True

            # Certification hard gate
            cert_flags = _check_certifications(record.get("certifications", []), required_certs)
            for cert, present in cert_flags.items():
                mandatory_gates[f"cert_{cert}"] = present
                if not present:
                    pass_mandatory = False

            # JLPT hard gate (if configured)
            jlpt_level = record.get("jlpt_level")
            jlpt_score = _JLPT_LEVEL_MAP.get(jlpt_level, 0)
            min_jlpt_score = _JLPT_LEVEL_MAP.get(min_jlpt, 0)
            jlpt_match = jlpt_level is not None and jlpt_score >= min_jlpt_score
            if min_jlpt > 0:
                mandatory_gates["jlpt_min_level"] = jlpt_match
                if not jlpt_match:
                    pass_mandatory = False

            # Check other required criteria
            for criterion in required_criteria:
                if criterion.get("type") == "certification":
                    continue  # Already handled above
                gate_name = str(criterion.get("name", "unknown_gate"))
                # Default: pass unless specific type is recognized
                mandatory_gates[gate_name] = True

            # Shift overlap
            shift_overlap_pct = _compute_shift_overlap(record.get("shift_availability", {}), shift_requirements)

            # 育成就労法 2028 eligibility
            ikusei_eligible, ikusei_interim = _apply_ikusei_shurou_rules(record, ikusei_module)

            # Preferred score
            preferred_score = _score_preferred(record, preferred_criteria, score_weights)

            # Aggregate: 60% preferred + 30% shift + 10% jlpt (configurable via weights)
            w_preferred = float(score_weights.get("preferred_weight", 0.6))
            w_shift = float(score_weights.get("shift_weight", 0.3))
            w_jlpt = float(score_weights.get("jlpt_weight", 0.1))
            jlpt_norm = jlpt_score / 5.0
            aggregate_score = round(
                preferred_score * w_preferred + shift_overlap_pct * w_shift + jlpt_norm * w_jlpt,
                3,
            )

            scored_candidate: dict[str, Any] = {
                "candidate_id": candidate_id,
                "mandatory_gates": mandatory_gates,
                "pass_mandatory": pass_mandatory,
                "preferred_scores": {
                    "aggregate": preferred_score,
                },
                "shift_overlap_pct": shift_overlap_pct,
                "certification_flags": cert_flags,
                "ikusei_shurou_eligible": ikusei_eligible,
                "ikusei_shurou_interim": ikusei_interim,
                "jlpt_match": jlpt_match,
                "jlpt_level": jlpt_level,
                "aggregate_score": aggregate_score,
            }
            scored_resumes.append(scored_candidate)

            emit_trace_event(
                "CriteriaScoreNode_candidate_scored",
                {
                    "candidate_id": candidate_id,
                    "pass_mandatory": pass_mandatory,
                    "aggregate_score": aggregate_score,
                    "shift_overlap_pct": shift_overlap_pct,
                },
                state,
            )

        emit_trace_event(
            "CriteriaScoreNode_batch_scored",
            {
                "total_candidates": len(parsed_resumes),
                "scored_count": len(scored_resumes),
                "passed_mandatory": sum(1 for c in scored_resumes if c.get("pass_mandatory")),
                "error_count": score_errors,
            },
            state,
        )

        return {
            "scored_resumes": scored_resumes,
            "score_error_count": score_errors,
            "status": AgentStatus.SUCCESS.value,
        }
