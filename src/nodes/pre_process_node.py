"""PreProcessNode — Validate resume screening payload and enforce S-2 input checks."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_INPUT_GUIDANCE = [
    "Send a JSON object with resume_batch, job_criteria, and job_id.",
    "resume_batch must be a non-empty list of supported resume references or encoded documents.",
    "job_criteria must describe required or preferred qualifications without embedding credentials.",
    'Each job_criteria entry must be an object, e.g. {"type": "certification", "name": "food_cert", "value": "\u98df\u54c1\u885b\u751f\u8cac\u4efb\u8005"}.',
]


def _input_error(message: str) -> dict[str, Any]:
    return {
        "status": AgentStatus.SUCCESS.value,
        "validated_input": "",
        "input_error_message": message,
        "input_error_guidance": _INPUT_GUIDANCE,
        "error_message": None,
    }


class PreProcessNode(FunctionNode):
    """Validate resume batch payload; enforce APPI-aware S-2 input checks.

    Blocks injection patterns, oversized payloads, and missing required fields
    before any PII-bearing resume content enters the pipeline.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.config: dict[str, Any] = dict(config or {})
        self._max_input_length = int(self.config.get("max_input_length", 500_000))
        self._max_batch_size = int(self.config.get("max_resumes_per_batch", 50))

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2: Reject oversized payloads, injection patterns, missing required keys."""
        user_input = state.get("user_input", {})
        if isinstance(user_input, dict):
            raw = json.dumps(user_input, ensure_ascii=False)
        else:
            raw = str(user_input)

        if len(raw) > self._max_input_length:
            raise SecurityViolationError(f"Input exceeds max_input_length={self._max_input_length}")

        lowered = raw.lower()
        for blocked in ["<script", "javascript:", "../", "..\\"]:
            if blocked in lowered:
                raise SecurityViolationError(f"Injection pattern detected: {blocked}")

        # Validate resume_batch is present
        batch = state.get("resume_batch", [])
        if not isinstance(batch, list):
            raise SecurityViolationError("resume_batch must be a list")
        if len(batch) > self._max_batch_size:
            raise SecurityViolationError(f"resume_batch size {len(batch)} exceeds max {self._max_batch_size}")

        # Reject credentials in payload
        payload = user_input if isinstance(user_input, dict) else {}
        if payload.get("credentials") or payload.get("api_key") or payload.get("token"):
            raise SecurityViolationError("Credentials must not be passed in state payload")
        return state

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", {})
        if isinstance(user_input, str):
            text = user_input.strip()
            if not text:
                return _input_error("Please provide the resume-screening payload as JSON.")
            try:
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    payload = {}
            except json.JSONDecodeError:
                payload = {}
        elif isinstance(user_input, dict):
            payload = user_input
        else:
            payload = {}

        # Allow resume_batch and job_criteria to be passed either via user_input
        # or directly in state (Cat 2 direct-state injection pattern)
        resume_batch = payload.get("resume_batch") or state.get("resume_batch", [])
        job_criteria = payload.get("job_criteria") or state.get("job_criteria", {})
        job_id = payload.get("job_id") or state.get("job_id", "")

        # Harness H6/G2: job_criteria's criterion lists must hold objects, not bare
        # strings. CriteriaScoreNode calls criterion.get(...) on each entry, so a
        # list of strings raised AttributeError deep inside the inner graph — the
        # run ended status=error and the Marketplace runner showed the caller a
        # bare RuntimeError with no reason. Reject it here, where the caller can
        # still be told what shape to send.
        if isinstance(job_criteria, dict):
            bad_lists = [
                key
                for key in ("required", "preferred", "shift_requirements")
                if any(not isinstance(item, dict) for item in (job_criteria.get(key) or []))
            ]
            if bad_lists:
                emit_trace_event(
                    "PreProcessNode_validation_failed",
                    {"invalid_criteria_lists": bad_lists},
                    state,
                )
                return _input_error("job_criteria entries must be objects, not plain text: " f"{', '.join(bad_lists)}.")

        required = {"resume_batch": resume_batch, "job_criteria": job_criteria, "job_id": job_id}
        missing = [k for k, v in required.items() if not v]
        if missing:
            emit_trace_event(
                "PreProcessNode_validation_failed",
                {"missing_keys": missing},
                state,
            )
            return _input_error(f"Missing required resume-screening fields: {', '.join(missing)}.")

        emit_trace_event(
            "PreProcessNode_execute_complete",
            {
                "resume_batch_size": len(resume_batch) if isinstance(resume_batch, list) else 0,
                "job_id": str(job_id),
            },
            state,
        )
        return {
            "resume_batch": resume_batch,
            "job_criteria": job_criteria,
            "job_id": str(job_id),
            "validated_input": json.dumps(
                {"job_id": job_id, "batch_size": len(resume_batch) if isinstance(resume_batch, list) else 0},
                ensure_ascii=False,
            ),
            "status": AgentStatus.SUCCESS.value,
            "error_message": None,
        }
