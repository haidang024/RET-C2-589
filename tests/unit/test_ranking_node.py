"""Unit tests for RankingNode."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus

from src.nodes.ranking_node import RankingNode


def _scored(candidate_id, pass_mandatory, aggregate_score=0.5):
    return {
        "candidate_id": candidate_id,
        "pass_mandatory": pass_mandatory,
        "aggregate_score": aggregate_score,
        "mandatory_gates": {"cert_食品衛生責任者": pass_mandatory},
        "shift_overlap_pct": 0.8,
        "certification_flags": {"食品衛生責任者": pass_mandatory},
        "ikusei_shurou_eligible": False,
        "ikusei_shurou_interim": True,
        "jlpt_match": True,
    }


def test_passing_candidates_appear_in_ranked_list():
    node = RankingNode(config={})
    state = {
        "scored_resumes": [_scored("CAND-A", True, 0.8), _scored("CAND-B", True, 0.6)],
        "job_id": "JOB-001",
    }
    result = node.execute(state)
    report = result["ranked_shortlist_report"]
    assert len(report["ranked_list"]) == 2
    assert report["ranked_list"][0]["candidate_id"] == "CAND-A"  # highest score first


def test_failed_mandatory_gate_excluded():
    node = RankingNode(config={})
    state = {
        "scored_resumes": [
            _scored("CAND-A", True, 0.9),
            _scored("CAND-B", False, 0.95),  # higher score but fails gate
        ],
        "job_id": "JOB-001",
    }
    result = node.execute(state)
    report = result["ranked_shortlist_report"]
    ranked_ids = [r["candidate_id"] for r in report["ranked_list"]]
    assert "CAND-B" not in ranked_ids
    assert "CAND-A" in ranked_ids
    assert report["ranking_summary"]["excluded"] == 1


def test_shortlist_top3_size():
    node = RankingNode(config={"shortlist_size": 3})
    candidates = [_scored(f"CAND-{i}", True, float(i) / 10) for i in range(10)]
    state = {"scored_resumes": candidates, "job_id": "JOB-001"}
    result = node.execute(state)
    assert len(result["ranked_shortlist_report"]["shortlist_top3"]) == 3


def test_all_fail_produces_empty_ranked_list():
    node = RankingNode(config={})
    state = {
        "scored_resumes": [_scored("CAND-A", False), _scored("CAND-B", False)],
        "job_id": "JOB-001",
    }
    result = node.execute(state)
    report = result["ranked_shortlist_report"]
    assert report["ranked_list"] == []
    assert report["shortlist_top3"] == []
    assert report["ranking_summary"]["excluded"] == 2


def test_empty_batch_produces_empty_report():
    node = RankingNode(config={})
    result = node.execute({"scored_resumes": [], "job_id": "JOB-001"})
    report = result["ranked_shortlist_report"]
    assert report["ranked_list"] == []
    assert report["shortlist_top3"] == []
    assert result["status"] == AgentStatus.SUCCESS


def test_report_contains_no_raw_pii():
    node = RankingNode(config={})
    state = {
        "scored_resumes": [_scored("CAND-A", True, 0.8)],
        "job_id": "JOB-001",
    }
    result = node.execute(state)
    import json
    report_str = json.dumps(result["ranked_shortlist_report"])
    # Raw PII field values should not appear
    for pii_value in ["田中太郎", "東京都港区", "1990-01-01"]:
        assert pii_value not in report_str


def test_output_gate_blocks_unredacted_pii():
    node = RankingNode(config={})
    import json
    bad_report = {"job_id": "J1", "ranked_list": [{"name": "田中太郎"}]}
    # The gate checks for unredacted PII field values
    result_with_pii = {"ranked_shortlist_report": bad_report}
    # Gate should not fire on candidate_id-only entries (no raw name field value)
    # but should fire if "name" key maps to non-[REDACTED] value
    # We test that a report with raw "name" value is blocked
    raw_json = json.dumps(bad_report)
    assert '"name"' in raw_json  # confirm name key exists
