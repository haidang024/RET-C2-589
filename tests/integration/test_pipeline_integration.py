"""Integration test: full 3-step resume screening pipeline for RET-C2-589."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from framework.schemas.agent_status import AgentStatus

from src.graph.domain_workflow_graph import DomainWorkflowGraph


def _make_resume(idx, has_food_cert=True, jlpt_level=3, shift_days=None):
    days = shift_days or ["月", "火", "水"]
    certs = ["食品衛生責任者"] if has_food_cert else []
    jlpt_text = f"N{jlpt_level}" if jlpt_level else ""
    cert_text = " ".join(certs)
    day_text = " ".join(days) + "勤務可能"
    return {
        "file_path": f"resume_{idx}.pdf",
        "content_text": f"{cert_text} {jlpt_text} {day_text}",
    }


def _make_state(resumes, job_id="JOB-001"):
    return {
        "caller_trust_level": "VERIFIED_EXTERNAL",
        "correlation_id": "test",
        "trace_id": "test",
        "session_id": "test",
        "thread_id": "test",
        "schema_version": "1",
        "retry_count": 0,
        "node_history": [],
        "error_log": [],
        "execution_time": {},
        "status": AgentStatus.SUCCESS,
        "user_input": "",
        "resume_batch": resumes,
        "job_criteria": {
            "required": [
                {"type": "certification", "name": "food_cert", "value": "食品衛生責任者"}
            ],
            "preferred": [],
            "shift_requirements": [{"day": "月"}, {"day": "火"}, {"day": "水"}],
            "min_jlpt_level": 0,
            "score_weights": {},
        },
        "job_id": job_id,
    }


def test_single_resume_happy_path():
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    state = _make_state([_make_resume(0, has_food_cert=True)])
    result = graph.invoke(state)
    assert result.get("status") == AgentStatus.SUCCESS
    assert "ranked_shortlist_report" in result
    report = result["ranked_shortlist_report"]
    assert report["ranking_summary"]["passed_gates"] == 1
    assert len(report["shortlist_top3"]) == 1


def test_batch_of_20_resumes():
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    resumes = [_make_resume(i, has_food_cert=(i % 2 == 0)) for i in range(20)]
    state = _make_state(resumes)
    result = graph.invoke(state)
    assert result.get("status") == AgentStatus.SUCCESS
    report = result["ranked_shortlist_report"]
    # 10 have cert (even indices), 10 don't
    assert report["ranking_summary"]["passed_gates"] == 10
    assert report["ranking_summary"]["excluded"] == 10
    assert len(report["shortlist_top3"]) == 3


def test_mandatory_gate_excludes_no_cert_candidates():
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    state = _make_state([
        _make_resume(0, has_food_cert=True),
        _make_resume(1, has_food_cert=False),
    ])
    result = graph.invoke(state)
    report = result["ranked_shortlist_report"]
    ranked_ids = [r["candidate_id"] for r in report["ranked_list"]]
    # Only the candidate with the cert should be in ranked list
    assert len(ranked_ids) == 1
    assert report["ranking_summary"]["excluded"] == 1


def test_empty_batch_produces_empty_report():
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    state = _make_state([])
    result = graph.invoke(state)
    assert result.get("status") == AgentStatus.SUCCESS
    report = result["ranked_shortlist_report"]
    assert report["ranked_list"] == []
    assert report["shortlist_top3"] == []


def test_all_fail_produces_empty_ranked_list():
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    resumes = [_make_resume(i, has_food_cert=False) for i in range(5)]
    state = _make_state(resumes)
    result = graph.invoke(state)
    report = result["ranked_shortlist_report"]
    assert report["ranked_list"] == []
    assert report["ranking_summary"]["excluded"] == 5


def test_pii_absent_from_final_output():
    import json
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    state = _make_state([_make_resume(0, has_food_cert=True)])
    result = graph.invoke(state)
    report_str = json.dumps(result.get("ranked_shortlist_report", {}), ensure_ascii=False)
    # Confirm no raw PII values leak into the report
    for pii_token in ["田中太郎", "090-1234", "1990-01-"]:
        assert pii_token not in report_str
