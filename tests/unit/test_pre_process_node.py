"""Unit tests for PreProcessNode."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus

from src.nodes.pre_process_node import PreProcessNode


def _make_state(**overrides):
    base = {
        "resume_batch": [{"file_path": "resume1.pdf", "content_text": "テスト履歴書"}],
        "job_criteria": {"required": [], "preferred": []},
        "job_id": "JOB-001",
    }
    base.update(overrides)
    return base


def test_valid_payload_passes():
    node = PreProcessNode(config={})
    result = node.execute(_make_state())
    assert result["status"] == AgentStatus.SUCCESS
    assert result["job_id"] == "JOB-001"
    assert result["resume_batch"] == [{"file_path": "resume1.pdf", "content_text": "テスト履歴書"}]


def test_missing_resume_batch_returns_guidance():
    node = PreProcessNode(config={})
    result = node.execute({"job_criteria": {}, "job_id": "JOB-001"})
    assert result["status"] == AgentStatus.SUCCESS
    assert "resume_batch" in result["input_error_message"]


def test_missing_job_id_returns_guidance():
    node = PreProcessNode(config={})
    result = node.execute({"resume_batch": [{}], "job_criteria": {}})
    assert result["status"] == AgentStatus.SUCCESS
    assert "job_id" in result["input_error_message"]


def test_injection_pattern_blocked():
    node = PreProcessNode(config={})
    with pytest.raises(SecurityViolationError, match="Injection pattern"):
        node._extra_security_gate_input(
            {"user_input": {"data": "<script>alert(1)</script>"}, "resume_batch": []}
        )


def test_path_traversal_in_user_input_blocked():
    node = PreProcessNode(config={})
    with pytest.raises(SecurityViolationError, match="Injection pattern"):
        node._extra_security_gate_input(
            {"user_input": {"path": "../../etc/passwd"}, "resume_batch": []}
        )


def test_oversized_payload_blocked():
    node = PreProcessNode(config={"max_input_length": 10})
    with pytest.raises(SecurityViolationError, match="max_input_length"):
        node._extra_security_gate_input(
            {"user_input": {"data": "x" * 100}, "resume_batch": []}
        )


def test_batch_size_limit_blocked():
    node = PreProcessNode(config={"max_resumes_per_batch": 2})
    with pytest.raises(SecurityViolationError, match="exceeds max"):
        node._extra_security_gate_input(
            {"user_input": {}, "resume_batch": [{}, {}, {}]}
        )


def test_credentials_in_payload_blocked():
    node = PreProcessNode(config={})
    with pytest.raises(SecurityViolationError, match="Credentials"):
        node._extra_security_gate_input(
            {"user_input": {"credentials": "secret123"}, "resume_batch": []}
        )
