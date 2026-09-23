"""PostProcessNode — Format RankedShortlistReport and enforce S-3 output checks."""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import provider_metadata

_CREDENTIAL_PATTERN = re.compile(r"\b(api[_-]?key|password|token|secret|jwt|bearer)\b", re.IGNORECASE)


class PostProcessNode(FunctionNode):
    """Finalize RankedShortlistReport output with S-3 output safety checks.

    Verifies the final report is non-empty and contains no credential-like
    content before returning to caller.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.config: dict[str, Any] = dict(config or {})

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3: Block empty output and credential-like content in report."""
        if result.get("input_error_message"):
            return result
        output = str(result.get("formatted_output", ""))
        if not output.strip():
            raise SecurityViolationError("Output is empty — blocked by S-3 gate")
        if _CREDENTIAL_PATTERN.search(output):
            raise SecurityViolationError("Credential-like content detected in formatted output")
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("input_error_message"):
            message = str(state["input_error_message"])
            return {
                "formatted_output": message,
                "result": message,
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": message,
            }
        report = state.get("ranked_shortlist_report")
        status = state.get("status", AgentStatus.SUCCESS.value)

        if report is None:
            emit_trace_event(
                "PostProcessNode_no_report",
                {"status": str(status)},
                state,
            )
            return {
                "formatted_output": json.dumps({"error": "No ranked_shortlist_report produced"}, ensure_ascii=False),
                "status": AgentStatus.ERROR.value,
                **provider_metadata(state),
            }

        summary = {
            "job_id": report.get("job_id", ""),
            "shortlist_top3": report.get("shortlist_top3", []),
            "ranking_summary": report.get("ranking_summary", {}),
            "generated_at": report.get("generated_at", ""),
        }
        formatted_output = json.dumps(summary, ensure_ascii=False, indent=2)

        # Inline S-3 gate: prevent credential patterns from escaping
        if _CREDENTIAL_PATTERN.search(formatted_output):
            raise SecurityViolationError("Credential-like content detected in formatted output")

        result = {
            "formatted_output": formatted_output,
            "status": AgentStatus.SUCCESS.value,
            **provider_metadata(state),
        }

        emit_trace_event(
            "PostProcessNode_execute_complete",
            {
                "shortlist_count": len(report.get("shortlist_top3", [])),
                "total_ranked": len(report.get("ranked_list", [])),
                "output_chars": len(formatted_output),
            },
            state,
        )
        return result
