"""Inner DomainWorkflowGraph for RET-C2-589 3-step resume screening pipeline."""

from __future__ import annotations

import json
from typing import Any, cast

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from langgraph.graph import END, START

from src.nodes.criteria_score_node import CriteriaScoreNode
from src.nodes.ranking_node import RankingNode
from src.nodes.resume_parse_node import ResumeParseNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner resume screening workflow graph.

    Pipeline: START → resume_parse → criteria_score → ranking → END
    Called by ResumeScreeningGraphNode.get_subgraph() in graph.py.
    """

    def __init__(self, config: dict[str, Any] | None = None, llm: Any = None) -> None:
        self._llm = llm
        super().__init__(config=config)

    @property
    def name(self) -> str:
        return "ret_c2_589_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        """No mandatory config keys — all have defaults."""
        pass

    def register_nodes(self) -> None:
        """Register domain nodes. No super() — BaseGraph.register_nodes() is abstract."""
        self._nodes["resume_parse"] = ResumeParseNode(config=self.config, llm=self._llm)
        self._nodes["criteria_score"] = CriteriaScoreNode(config=self.config)
        self._nodes["ranking"] = RankingNode(config=self.config)

    def add_edges(self) -> None:
        """Wire linear 3-step topology."""
        self._sg.add_edge(START, "resume_parse")
        self._sg.add_edge("resume_parse", "criteria_score")
        self._sg.add_edge("criteria_score", "ranking")
        self._sg.add_edge("ranking", END)

    def invoke(
        self,
        user_input: Any,
        session_id: str = "",
        ctx: InvocationContext | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Accept legacy direct-state tests while using AgentCore 1.0 invocation state."""
        if isinstance(user_input, dict):
            legacy_state = user_input
            if ctx is None:
                ctx = InvocationContext(
                    correlation_id=str(legacy_state.get("correlation_id", "test")),
                    session_id=str(legacy_state.get("session_id", session_id or "test")),
                    thread_id=str(legacy_state.get("thread_id", "test")),
                    caller_trust_level=TrustLevel(
                        legacy_state.get("caller_trust_level", TrustLevel.VERIFIED_EXTERNAL.value)
                    ),
                )
            user_input = json.dumps(
                {
                    "resume_batch": legacy_state.get("resume_batch", []),
                    "job_criteria": legacy_state.get("job_criteria", {}),
                    "job_id": legacy_state.get("job_id", ""),
                },
                ensure_ascii=False,
            )
        return cast(
            dict[str, Any],
            super().invoke(user_input, session_id=session_id, ctx=ctx, input_context=input_context),
        )

    def route(self, state: AgentState) -> str:
        """Required by BaseGraph ABC. Linear topology — never called conditionally."""
        return str(END) if state.get("status") == AgentStatus.ERROR.value else "criteria_score"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        """Shape sub_result for ResumeScreeningGraphNode.merge_output()."""
        return {
            "generation_mode": state.get("generation_mode"),
            "provider_error_message": state.get("provider_error_message"),
            "parsed_resumes": state.get("parsed_resumes", []),
            "scored_resumes": state.get("scored_resumes", []),
            "ranked_shortlist_report": state.get("ranked_shortlist_report"),
            "parse_error_count": state.get("parse_error_count", 0),
            "score_error_count": state.get("score_error_count", 0),
            "status": state.get("status", AgentStatus.SUCCESS.value),
            "output": state.get("ranked_shortlist_report"),
            "trace_id": state.get("trace_id", ""),
            "correlation_id": state.get("correlation_id", ""),
            "node_history": state.get("node_history", []),
        }
