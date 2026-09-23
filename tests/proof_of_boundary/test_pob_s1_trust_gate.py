"""PoB test 1 (instructions/8.md): S-1 trust level gate on ResumeParseNode."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.schemas.trust_level import TrustLevel

from src.nodes.resume_parse_node import ResumeParseNode


def test_node_declares_verified_external_trust_level() -> None:
    """S-1: ResumeParseNode must require VERIFIED_EXTERNAL trust level."""
    assert ResumeParseNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL


def test_node_proceeds_with_valid_trust_level() -> None:
    """Calling execute() with valid input succeeds (trust is checked by __call__)."""
    node = ResumeParseNode(config={})
    result = node.execute({
        "resume_batch": [{"file_path": "r.pdf", "content_text": "食品衛生責任者"}],
        "job_id": "JOB-001",
    })
    from framework.schemas.agent_status import AgentStatus
    assert result["status"] == AgentStatus.SUCCESS


def test_trust_level_value_is_higher_than_anonymous() -> None:
    """S-1: VERIFIED_EXTERNAL > ANONYMOUS (int comparison enforced by framework)."""
    assert TrustLevel.VERIFIED_EXTERNAL > TrustLevel.ANONYMOUS
