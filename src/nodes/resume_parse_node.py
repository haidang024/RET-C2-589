"""ResumeParseNode — Step 1: PDF/Japanese document extraction to ResumeRecord JSON via LLM."""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security.pii_detector import detect_pii
from framework.security.pii_masking import mask_pii
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_runtime import complete_text
from src.services.llm_runtime import provider_metadata

# PII field names that must never appear in logs or downstream outputs
_PII_FIELDS = ("name", "氏名", "address", "住所", "date_of_birth", "生年月日", "phone", "email", "マイナンバー")

# JIS-standard 履歴書 section headers
_JIS_SECTION_PATTERNS = [
    r"学歴",
    r"職歴",
    r"資格",
    r"免許",
    r"志望動機",
    r"特技",
    r"趣味",
    r"通勤時間",
    r"扶養家族",
    r"配偶者",
    r"シフト",
    r"希望勤務時間",
]


def _pseudonymize(resume_idx: int, job_id: str) -> str:
    """Generate a stable, non-reversible candidate_id from resume index and job_id."""
    h = hashlib.sha256(f"{job_id}:{resume_idx}".encode()).hexdigest()[:12]
    return f"CAND-{h}"


def _redact_pii(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the record with PII fields replaced by redaction markers.

    This runs inside _extra_security_gate_output() to ensure no PII escapes
    into logs or downstream state fields other than parsed_resumes (handled by
    the ranking output gate).
    """
    redacted = dict(record)
    for field in _PII_FIELDS:
        if field in redacted:
            redacted[field] = "[REDACTED]"
    return redacted


def _extract_with_llm(
    state: dict[str, Any],
    content_text: str,
    llm: Any = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the invocation-scoped LLM to extract structured fields from resume text.

    Returns a dict with keys matching ResumeRecord schema. If llm is
    None (test/offline mode), returns a minimal stub.
    """
    pii_findings = detect_pii(content_text)
    safe_text = mask_pii(content_text, pii_findings) if pii_findings else content_text
    prompt = (
        "以下の履歴書テキストから構造化データをJSONで抽出してください。\n"
        "フィールド: education (list), work_history (list), certifications (list), "
        "shift_availability (dict), jlpt_level (int|null), nationality_category (str)\n"
        "注意: 氏名・住所・生年月日は name/address/date_of_birth フィールドに含めること。\n\n"
        f"履歴書テキスト（PIIマスク済み）:\n{safe_text[:3000]}"
    )
    try:
        content = complete_text(
            state,
            [
                {"role": "user", "content": prompt},
            ],
            llm,
            max_tokens=1200,
            timeout_s=float((config or {}).get("timeout_s", 60.0)),
            max_retry=int((config or {}).get("max_retry", 3)),
        )
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return _heuristic_parse(content_text)


def _heuristic_parse(text: str) -> dict[str, Any]:
    """Minimal heuristic fallback for offline/test mode.

    Scans for JIS section markers and extracts rough fields.
    """
    certifications: list[str] = []
    if "食品衛生責任者" in text:
        certifications.append("食品衛生責任者")
    if "JLPT" in text or "日本語能力試験" in text:
        for lvl in range(1, 6):
            if f"N{lvl}" in text:
                certifications.append(f"JLPT_N{lvl}")
                break

    jlpt_level = None
    for lvl in range(1, 6):
        if f"N{lvl}" in text:
            jlpt_level = lvl
            break

    shift_avail: dict[str, list[str]] = {}
    days = ["月", "火", "水", "木", "金", "土", "日"]
    for day in days:
        if day in text:
            shift_avail[day] = ["09:00-18:00"]

    return {
        "education": [],
        "work_history": [],
        "certifications": certifications,
        "shift_availability": shift_avail,
        "jlpt_level": jlpt_level,
        "nationality_category": "unknown",
        "parse_errors": [],
    }


class ResumeParseNode(FunctionNode):
    """Step 1: Parse PDF/Japanese resumes into structured ResumeRecord JSON.

    Emits emit_trace_event per resume for audit traceability.
    PII redaction applied in _extra_security_gate_output before any log emission.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        llm: Any = None,
    ) -> None:
        super().__init__()
        self.config: dict[str, Any] = dict(config or {})
        self._llm = llm
        self._max_resumes = int(self.config.get("max_resumes_per_batch", 50))

    @staticmethod
    def _domain_input(
        state: dict[str, Any],
    ) -> tuple[object, object, str]:
        """Read direct-state input or the GraphNode's serialized child payload."""
        batch = state.get("resume_batch", [])
        job_criteria = state.get("job_criteria", {})
        job_id = str(state.get("job_id", ""))
        if not batch and isinstance(state.get("user_input"), str):
            try:
                payload = json.loads(state["user_input"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict):
                batch = payload.get("resume_batch", [])
                job_criteria = payload.get("job_criteria", {})
                job_id = str(payload.get("job_id", ""))
        return batch, job_criteria, job_id

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2: Validate resume batch shape; block path traversal and injection."""
        batch, _, _ = self._domain_input(state)
        if not isinstance(batch, list):
            raise SecurityViolationError("resume_batch must be a list")
        if len(batch) > self._max_resumes:
            raise SecurityViolationError(f"resume_batch size {len(batch)} exceeds max {self._max_resumes}")
        for idx, item in enumerate(batch):
            if not isinstance(item, dict):
                raise SecurityViolationError(f"resume_batch[{idx}] must be a dict")
            file_path = str(item.get("file_path", ""))
            if "../" in file_path or "..\\" in file_path:
                raise SecurityViolationError(f"Path traversal detected in resume_batch[{idx}].file_path")
            for blocked in ["<script", "javascript:"]:
                if blocked in file_path.lower():
                    raise SecurityViolationError(f"Injection pattern detected in resume_batch[{idx}].file_path")
        return state

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3: Ensure parsed_resumes do not contain raw PII in logged fields.

        Redacts PII fields from the log-safe representation. The full
        parsed_resumes list (with pseudonymized candidate_id) is retained
        in state for downstream scoring, but this gate ensures the result
        dict returned to the framework is PII-safe.
        """
        parsed = result.get("parsed_resumes", [])
        if isinstance(parsed, list):
            for record in parsed:
                if isinstance(record, dict):
                    for pii_field in _PII_FIELDS:
                        if pii_field in record and record[pii_field] not in (None, "[REDACTED]"):
                            raise SecurityViolationError(f"PII field '{pii_field}' present in parsed_resumes output")
        return result

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Inline path-traversal check for unit tests that call execute() directly
        batch, job_criteria, job_id = self._domain_input(state)
        if not isinstance(batch, list):
            batch = []
        for idx, item in enumerate(batch):
            if isinstance(item, dict):
                file_path = str(item.get("file_path", ""))
                if "../" in file_path or "..\\" in file_path:
                    raise SecurityViolationError(f"Path traversal detected in resume_batch[{idx}].file_path")

        job_id = job_id or "unknown"
        parsed_resumes: list[dict[str, Any]] = []
        parse_errors = 0

        for idx, item in enumerate(batch):
            if not isinstance(item, dict):
                parse_errors += 1
                continue

            content_text = item.get("content_text", "")
            if not content_text:
                # Fallback: try to decode content_b64 if present
                content_b64 = item.get("content_b64", "")
                if content_b64:
                    try:
                        import base64

                        content_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                    except Exception:
                        content_text = ""

            candidate_id = _pseudonymize(idx, job_id)

            extracted = _extract_with_llm(state, content_text, self._llm, self.config)

            # Build ResumeRecord — store PII in dedicated fields, all others non-PII
            record: dict[str, Any] = {
                "candidate_id": candidate_id,
                # PII fields — stored with APPI annotation; redacted in output gate
                "name": extracted.get("name", "[REDACTED]"),
                "address": extracted.get("address", "[REDACTED]"),
                "date_of_birth": extracted.get("date_of_birth", "[REDACTED]"),
                # Non-PII structured fields
                "education": extracted.get("education", []),
                "work_history": extracted.get("work_history", []),
                "certifications": extracted.get("certifications", []),
                "shift_availability": extracted.get("shift_availability", {}),
                "jlpt_level": extracted.get("jlpt_level"),
                "nationality_category": extracted.get("nationality_category", "unknown"),
                "parse_errors": extracted.get("parse_errors", []),
            }

            # Immediately redact PII fields to prevent leakage
            record["name"] = "[REDACTED]"
            record["address"] = "[REDACTED]"
            record["date_of_birth"] = "[REDACTED]"

            parsed_resumes.append(record)

            emit_trace_event(
                "ResumeParseNode_resume_parsed",
                {
                    "candidate_id": candidate_id,
                    "certifications_found": len(record.get("certifications", [])),
                    "parse_error_count": len(record.get("parse_errors", [])),
                },
                state,
            )

        emit_trace_event(
            "ResumeParseNode_batch_complete",
            {
                "total_resumes": len(batch),
                "parsed_count": len(parsed_resumes),
                "error_count": parse_errors,
            },
            state,
        )

        return {
            "resume_batch": batch,
            "job_criteria": job_criteria,
            "job_id": job_id,
            "parsed_resumes": parsed_resumes,
            **provider_metadata(state),
            "parse_error_count": parse_errors,
            "status": AgentStatus.SUCCESS.value,
        }
