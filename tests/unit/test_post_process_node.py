"""Unit tests for PostProcessNode."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus

from src.nodes.post_process_node import PostProcessNode


def _report(job_id="JOB-001", shortlist=None):
    return {
        "job_id": job_id,
        "shortlist_top3": shortlist or [{"candidate_id": "CAND-A", "rank": 1}],
        "ranked_list": shortlist or [{"candidate_id": "CAND-A", "rank": 1}],
        "pii_redacted_compliance_log": [],
        "ranking_summary": {"total": 1, "passed_gates": 1, "excluded": 0, "shortlist_size": 1},
        "generated_at": "2026-07-08T00:00:00+00:00",
    }


def test_valid_report_produces_formatted_output():
    node = PostProcessNode(config={})
    result = node.execute({"ranked_shortlist_report": _report()})
    assert result["status"] == AgentStatus.SUCCESS
    assert "JOB-001" in result["formatted_output"]
    assert "shortlist_top3" in result["formatted_output"]


def test_none_report_returns_error():
    node = PostProcessNode(config={})
    result = node.execute({"ranked_shortlist_report": None})
    assert result["status"] == AgentStatus.ERROR


def test_output_gate_blocks_empty_output():
    node = PostProcessNode(config={})
    with pytest.raises(SecurityViolationError, match="empty"):
        node._extra_security_gate_output({"formatted_output": ""})


def test_output_gate_blocks_credential_pattern():
    node = PostProcessNode(config={})
    with pytest.raises(SecurityViolationError, match="Credential"):
        node._extra_security_gate_output({"formatted_output": '{"api_key": "abc123"}'})


def test_output_gate_allows_clean_output():
    node = PostProcessNode(config={})
    result = node._extra_security_gate_output({"formatted_output": '{"job_id": "JOB-001"}'})
    assert result["formatted_output"] == '{"job_id": "JOB-001"}'
