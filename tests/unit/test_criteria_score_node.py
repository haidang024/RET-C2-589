"""Unit tests for CriteriaScoreNode."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus

from src.nodes.criteria_score_node import CriteriaScoreNode


def _candidate(candidate_id="CAND-001", certifications=None, jlpt_level=None, shift_availability=None):
    return {
        "candidate_id": candidate_id,
        "certifications": certifications or [],
        "jlpt_level": jlpt_level,
        "shift_availability": shift_availability or {},
        "work_history": [],
        "education": [],
        "parse_errors": [],
    }


def _criteria(required_certs=None, preferred=None, shifts=None, min_jlpt=0):
    return {
        "required": [
            {"type": "certification", "name": "food_cert", "value": c}
            for c in (required_certs or [])
        ],
        "preferred": preferred or [],
        "shift_requirements": shifts or [],
        "min_jlpt_level": min_jlpt,
        "score_weights": {},
    }


def test_passes_mandatory_with_required_cert():
    node = CriteriaScoreNode(config={})
    state = {
        "parsed_resumes": [_candidate(certifications=["食品衛生責任者"])],
        "job_criteria": _criteria(required_certs=["食品衛生責任者"]),
    }
    result = node.execute(state)
    assert result["status"] == AgentStatus.SUCCESS
    scored = result["scored_resumes"][0]
    assert scored["pass_mandatory"] is True
    assert scored["certification_flags"]["食品衛生責任者"] is True


def test_fails_mandatory_without_required_cert():
    node = CriteriaScoreNode(config={})
    state = {
        "parsed_resumes": [_candidate(certifications=[])],
        "job_criteria": _criteria(required_certs=["食品衛生責任者"]),
    }
    result = node.execute(state)
    scored = result["scored_resumes"][0]
    assert scored["pass_mandatory"] is False
    assert scored["certification_flags"]["食品衛生責任者"] is False


def test_shift_overlap_full_match():
    node = CriteriaScoreNode(config={})
    shifts = [{"day": "月"}, {"day": "火"}, {"day": "水"}]
    avail = {"月": ["09:00-18:00"], "火": ["09:00-18:00"], "水": ["09:00-18:00"]}
    state = {
        "parsed_resumes": [_candidate(shift_availability=avail)],
        "job_criteria": _criteria(shifts=shifts),
    }
    result = node.execute(state)
    assert result["scored_resumes"][0]["shift_overlap_pct"] == 1.0


def test_shift_overlap_partial():
    node = CriteriaScoreNode(config={})
    shifts = [{"day": "月"}, {"day": "火"}, {"day": "水"}, {"day": "木"}, {"day": "金"}]
    avail = {"月": ["09:00-18:00"], "火": ["09:00-18:00"], "水": ["09:00-18:00"]}
    state = {
        "parsed_resumes": [_candidate(shift_availability=avail)],
        "job_criteria": _criteria(shifts=shifts),
    }
    result = node.execute(state)
    assert result["scored_resumes"][0]["shift_overlap_pct"] == pytest.approx(0.6, abs=0.01)


def test_shift_overlap_no_match():
    node = CriteriaScoreNode(config={})
    shifts = [{"day": "月"}, {"day": "火"}]
    avail = {"土": ["09:00-18:00"], "日": ["09:00-18:00"]}
    state = {
        "parsed_resumes": [_candidate(shift_availability=avail)],
        "job_criteria": _criteria(shifts=shifts),
    }
    result = node.execute(state)
    assert result["scored_resumes"][0]["shift_overlap_pct"] == 0.0


def test_jlpt_match_above_minimum():
    node = CriteriaScoreNode(config={})
    state = {
        "parsed_resumes": [_candidate(jlpt_level=2)],
        "job_criteria": _criteria(min_jlpt=3),
    }
    result = node.execute(state)
    assert result["scored_resumes"][0]["jlpt_match"] is True


def test_jlpt_match_below_minimum():
    node = CriteriaScoreNode(config={})
    state = {
        "parsed_resumes": [_candidate(jlpt_level=5)],
        "job_criteria": _criteria(min_jlpt=3),
    }
    result = node.execute(state)
    scored = result["scored_resumes"][0]
    assert scored["jlpt_match"] is False
    assert scored["pass_mandatory"] is False


def test_ikusei_shurou_defaults_to_interim():
    node = CriteriaScoreNode(config={})
    state = {
        "parsed_resumes": [_candidate()],
        "job_criteria": _criteria(),
    }
    result = node.execute(state)
    scored = result["scored_resumes"][0]
    assert scored["ikusei_shurou_interim"] is True


def test_output_gate_blocks_pii_in_scored_resumes():
    node = CriteriaScoreNode(config={})
    with pytest.raises(SecurityViolationError, match="PII field"):
        node._extra_security_gate_output({
            "scored_resumes": [{"name": "田中太郎", "candidate_id": "CAND-001"}]
        })


def test_empty_parsed_resumes_returns_empty_scored():
    node = CriteriaScoreNode(config={})
    result = node.execute({"parsed_resumes": [], "job_criteria": _criteria()})
    assert result["scored_resumes"] == []
    assert result["status"] == AgentStatus.SUCCESS
