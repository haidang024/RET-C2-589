"""PoB test 2 (instructions/9.md): APPI PII redaction in node outputs and trace logs."""

from __future__ import annotations

import json
import pytest

pytest.importorskip("framework")

from framework.schemas.agent_status import AgentStatus

from src.nodes.resume_parse_node import ResumeParseNode
from src.nodes.criteria_score_node import CriteriaScoreNode
from src.nodes.ranking_node import RankingNode


_KNOWN_PII = ["田中太郎", "東京都港区1-2-3", "1990-01-15", "090-1234-5678", "tanaka@example.com"]


def test_parsed_resumes_pii_fields_are_redacted() -> None:
    """S-3/S-4: parsed_resumes must not contain raw PII field values."""
    node = ResumeParseNode(config={})
    # Inject known PII strings into the resume content
    pii_text = "田中太郎 東京都港区1-2-3 1990-01-15 090-1234-5678 tanaka@example.com 食品衛生責任者"
    result = node.execute({
        "resume_batch": [{"file_path": "resume.pdf", "content_text": pii_text}],
        "job_id": "JOB-001",
    })
    assert result["status"] == AgentStatus.SUCCESS
    parsed_str = json.dumps(result["parsed_resumes"], ensure_ascii=False)

    # Raw PII values must not appear in the serialized output
    for pii_value in _KNOWN_PII:
        assert pii_value not in parsed_str, (
            f"PII value '{pii_value}' found in parsed_resumes output"
        )

    # Redaction markers must be present
    assert "[REDACTED]" in parsed_str


def test_emit_trace_event_logs_do_not_contain_pii() -> None:
    """S-4: trace event payloads must not log raw PII tokens."""
    import src.nodes.resume_parse_node as mod

    captured_payloads: list[dict] = []
    original = mod.emit_trace_event

    mod.emit_trace_event = lambda name, payload, state: captured_payloads.append(payload)

    try:
        node = ResumeParseNode(config={})
        pii_text = "田中太郎 1990-01-15 090-1234-5678"
        node.execute({
            "resume_batch": [{"file_path": "r.pdf", "content_text": pii_text}],
            "job_id": "JOB-001",
        })
    finally:
        mod.emit_trace_event = original

    all_payload_str = json.dumps(captured_payloads, ensure_ascii=False)
    for pii_value in _KNOWN_PII:
        assert pii_value not in all_payload_str, (
            f"PII value '{pii_value}' found in trace event payloads"
        )


def test_ranked_shortlist_report_pii_absent() -> None:
    """RankedShortlistReport output must not contain raw PII fields."""
    # Build a scored_resumes list with only pseudonymized candidate IDs
    score_node = CriteriaScoreNode(config={})
    parse_result = {
        "parsed_resumes": [
            {
                "candidate_id": "CAND-abc123",
                "name": "[REDACTED]",
                "address": "[REDACTED]",
                "date_of_birth": "[REDACTED]",
                "certifications": ["食品衛生責任者"],
                "shift_availability": {"月": ["09:00-18:00"]},
                "jlpt_level": 3,
                "work_history": [],
                "education": [],
                "parse_errors": [],
                "nationality_category": "unknown",
            }
        ],
        "job_criteria": {
            "required": [{"type": "certification", "name": "food_cert", "value": "食品衛生責任者"}],
            "preferred": [],
            "shift_requirements": [{"day": "月"}],
            "min_jlpt_level": 0,
            "score_weights": {},
        },
    }
    scored = score_node.execute(parse_result)

    rank_node = RankingNode(config={})
    rank_result = rank_node.execute({
        "scored_resumes": scored["scored_resumes"],
        "job_id": "JOB-001",
    })

    report_str = json.dumps(rank_result["ranked_shortlist_report"], ensure_ascii=False)
    for pii_value in _KNOWN_PII:
        assert pii_value not in report_str, (
            f"PII value '{pii_value}' found in ranked_shortlist_report"
        )
