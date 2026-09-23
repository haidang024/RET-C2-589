"""Unit tests for ResumeParseNode."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus

from src.nodes.resume_parse_node import ResumeParseNode


class _FakeLlm:
    def complete(self, messages):
        assert messages[0]["role"] == "user"
        return {
            "content": (
                '{"education": [], "work_history": [], '
                '"certifications": ["食品衛生責任者"], '
                '"shift_availability": {}, "jlpt_level": 2}'
            )
        }


def _base_state(batch=None, job_id="JOB-001"):
    return {
        "resume_batch": batch or [],
        "job_id": job_id,
        "job_criteria": {},
    }


def test_valid_single_resume_is_parsed():
    node = ResumeParseNode(config={})
    state = _base_state(batch=[{
        "file_path": "resume.pdf",
        "content_text": "食品衛生責任者 N3 月火水木金勤務可能",
    }])
    result = node.execute(state)
    assert result["status"] == AgentStatus.SUCCESS
    assert len(result["parsed_resumes"]) == 1
    candidate = result["parsed_resumes"][0]
    assert candidate["candidate_id"].startswith("CAND-")
    assert "食品衛生責任者" in candidate["certifications"]


def test_pii_fields_are_redacted():
    node = ResumeParseNode(config={})
    state = _base_state(batch=[{
        "file_path": "resume.pdf",
        "content_text": "田中太郎 東京都港区 1990-01-01",
    }])
    result = node.execute(state)
    candidate = result["parsed_resumes"][0]
    assert candidate["name"] == "[REDACTED]"
    assert candidate["address"] == "[REDACTED]"
    assert candidate["date_of_birth"] == "[REDACTED]"


def test_jlpt_extracted_from_text():
    node = ResumeParseNode(config={})
    state = _base_state(batch=[{"file_path": "r.pdf", "content_text": "日本語能力試験 N2 合格"}])
    result = node.execute(state)
    assert result["parsed_resumes"][0]["jlpt_level"] == 2


def test_injected_llm_is_used_for_resume_extraction():
    node = ResumeParseNode(config={}, llm=_FakeLlm())
    result = node.execute(
        _base_state(batch=[{"file_path": "r.pdf", "content_text": "unstructured"}])
    )
    candidate = result["parsed_resumes"][0]
    assert candidate["jlpt_level"] == 2
    assert candidate["certifications"] == ["食品衛生責任者"]


def test_empty_batch_returns_empty_list():
    node = ResumeParseNode(config={})
    result = node.execute(_base_state(batch=[]))
    assert result["status"] == AgentStatus.SUCCESS
    assert result["parsed_resumes"] == []
    assert result["parse_error_count"] == 0


def test_malformed_item_counted_as_error():
    node = ResumeParseNode(config={})
    result = node.execute(_base_state(batch=["not-a-dict"]))
    assert result["parse_error_count"] == 1


def test_path_traversal_blocked_in_execute():
    node = ResumeParseNode(config={})
    with pytest.raises(SecurityViolationError, match="Path traversal"):
        node.execute(_base_state(batch=[{"file_path": "../../etc/passwd", "content_text": ""}]))


def test_extra_security_gate_output_blocks_unredacted_pii():
    node = ResumeParseNode(config={})
    with pytest.raises(SecurityViolationError, match="PII field"):
        node._extra_security_gate_output({
            "parsed_resumes": [{"name": "田中太郎", "candidate_id": "CAND-abc"}]
        })


def test_batch_size_limit_enforced_in_gate():
    node = ResumeParseNode(config={"max_resumes_per_batch": 2})
    with pytest.raises(SecurityViolationError, match="exceeds max"):
        node._extra_security_gate_input({
            "resume_batch": [{}, {}, {}],
            "job_id": "J1",
        })
