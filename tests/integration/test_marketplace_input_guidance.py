import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


def test_invalid_marketplace_request_returns_readable_guidance():
    graph = Graph(config={})
    graph.compile()
    result = graph.invoke(
        "Hello, hi",
        ctx=InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL),
        input_context={"conversation_history": []},
    )

    assert result["status"] == "success"
    assert result["output"].startswith("Resume-screening request could not be processed.")
    assert "Reason:" in result["output"]
    assert "How to continue:" in result["output"]


def test_success_output_is_readable_only_for_marketplace():
    graph = Graph(config={})
    canonical = json.dumps(
        {
            "job_id": "JOB-001",
            "shortlist_top3": [{"candidate_id": "CAND-A", "rank": 1, "aggregate_score": 0.91}],
            "ranking_summary": {"total": 4, "passed_gates": 2, "excluded": 2, "shortlist_size": 2},
            "generated_at": "2026-08-26T00:00:00+00:00",
        }
    )
    state = {"formatted_output": canonical, "status": "success"}

    assert graph.get_output(state)["output"] == canonical

    marketplace = graph.get_output({**state, "input_context": {"conversation_history": []}})
    assert marketplace["output"].startswith("# Resume Screening Shortlist")
    assert "CAND-A" in marketplace["output"]
    assert "human hiring review" in marketplace["output"]
    assert not marketplace["output"].lstrip().startswith("{")
