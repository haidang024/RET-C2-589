"""State schema for RET-C2-589 RetailPartTimeResumeScreeningAgent."""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption. Extend AgentState with agent-specific
# fields only. Do NOT add credentials, secrets, or Pydantic models.
#
# APPI note: resume_batch contains raw PII (name, address, DOB).
# These fields must be handled by ResumeParseNode with PII redaction
# before downstream processing. Annotated with sensitivity level below.

from __future__ import annotations

from typing import Any, Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Flat, JSON-safe state contract for RET-C2-589 resume screening workflow.

    PII sensitivity levels:
    - resume_batch: HIGH — raw PDF bytes or file paths; APPI-protected
    - parsed_resumes: HIGH — structured PII fields extracted from resumes
    - scored_resumes: MEDIUM — scores and flags; must not contain raw PII
    - ranked_shortlist_report: LOW — PII-redacted ranking output for callers
    """

    # ── Input (required) ──────────────────────────────────────────────────────
    # resume_batch: list of dicts with keys: {"file_path": str, "content_b64": str}
    # APPI sensitivity: HIGH — contains raw PII (氏名, 住所, 生年月日)
    resume_batch: list[dict[str, Any]]

    # job_criteria: dict with keys: {"required": list[dict], "preferred": list[dict],
    #   "shift_requirements": list[dict], "min_jlpt_level": int,
    #   "ikusei_shurou_rules_module": str, "score_weights": dict}
    job_criteria: dict[str, Any]

    # job_id: unique identifier for the job requisition
    job_id: str

    # ── Step 1: ResumeParseNode output ────────────────────────────────────────
    # parsed_resumes: list[dict] — each dict is a ResumeRecord (JSON-safe)
    # ResumeRecord keys: {candidate_id, name_redacted, education, work_history,
    #   certifications, shift_availability, jlpt_level, nationality_category,
    #   raw_text_redacted, parse_errors}
    # APPI sensitivity: HIGH — structured PII; PII-redacted before output gates
    parsed_resumes: list[dict[str, Any]]

    # ── Step 2: CriteriaScoreNode output ─────────────────────────────────────
    # scored_resumes: list[dict] — each dict is a ScoredCandidate (JSON-safe)
    # ScoredCandidate keys: {candidate_id, mandatory_gates, preferred_scores,
    #   shift_overlap_pct, certification_flags, ikusei_shurou_eligible,
    #   ikusei_shurou_interim, jlpt_match, aggregate_score, pass_mandatory}
    # APPI sensitivity: MEDIUM — no raw PII; candidate_id is pseudonym
    scored_resumes: list[dict[str, Any]]

    # ── Step 3: RankingNode output ────────────────────────────────────────────
    # ranked_shortlist_report: dict — RankedShortlistReport (JSON-safe)
    # Keys: {job_id, ranked_list, shortlist_top3, pii_redacted_compliance_log,
    #   ranking_summary, generated_at}
    # APPI sensitivity: LOW — PII-redacted output safe for caller consumption
    ranked_shortlist_report: Optional[dict[str, Any]]

    # ── Processing metadata ───────────────────────────────────────────────────
    parse_error_count: Optional[int]
    score_error_count: Optional[int]
    input_error_message: str | None
    input_error_guidance: list[str]
    generation_mode: str | None
    provider_error_message: str | None
