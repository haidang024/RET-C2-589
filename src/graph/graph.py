"""Outer Graph for RET-C2-589 — Cat 2 RetailPartTimeResumeScreeningAgent."""

from __future__ import annotations

import json
from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.graph.base_graph import BaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class ResumeScreeningGraphNode(GraphNode):
    """GraphNode wrapper for the inner resume screening workflow graph."""

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._llm = llm

    def get_subgraph(self) -> BaseGraph:
        """Build a fresh compiled child graph for this invocation.

        Node instances are shared across invocations
        via the registry's LRU cache, so caching the compiled subgraph on ``self``
        would share one graph (and its per-run state) between concurrent callers.
        Construction is cheap relative to the screening work, so build per call.
        """
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        child = DomainWorkflowGraph(config=self._parent_config(), llm=self._llm)
        child.compile()
        return child

    def extract_input(self, state: AgentState) -> str:
        """Serialize the domain payload for the child graph invocation boundary."""
        return json.dumps(
            {
                "resume_batch": state.get("resume_batch", []),
                "job_criteria": state.get("job_criteria", {}),
                "job_id": state.get("job_id", ""),
            },
            ensure_ascii=False,
        )

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("input_error_message"):
            return {"status": AgentStatus.SUCCESS.value}
        return cast(dict[str, Any], super().execute(state))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Map inner graph output back into the outer state."""
        del state
        return {
            "generation_mode": sub_result.get("generation_mode"),
            "provider_error_message": sub_result.get("provider_error_message"),
            "parsed_resumes": sub_result.get("parsed_resumes", []),
            "scored_resumes": sub_result.get("scored_resumes", []),
            "ranked_shortlist_report": sub_result.get("ranked_shortlist_report"),
            "parse_error_count": sub_result.get("parse_error_count", 0),
            "score_error_count": sub_result.get("score_error_count", 0),
            "status": sub_result.get("status", AgentStatus.SUCCESS.value),
        }

    def _parent_config(self) -> dict[str, Any]:
        """Forward config keys the inner graph needs."""
        cfg = self.config
        return {
            "max_resumes_per_batch": int(cfg.get("max_resumes_per_batch", 50)),
            "min_jlpt_level": int(cfg.get("min_jlpt_level", 0)),
            "shortlist_size": int(cfg.get("shortlist_size", 3)),
            "ikusei_shurou_rules_module": cfg.get("ikusei_shurou_rules_module"),
            "timeout_s": cfg.get("timeout_s", 60.0),
            "max_retry": cfg.get("max_retry", 3),
        }


class Graph(AgentBaseGraph):
    """Outer Cat-2 AgentBaseGraph for RET-C2-589 RetailPartTimeResumeScreeningAgent."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    @property
    def name(self) -> str:
        return "ret_c2_589"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = PreProcessNode(config=self.config)
        self._nodes["main"] = ResumeScreeningGraphNode(
            llm=self.config.get("llm"),
            config=self.config,
        )
        self._nodes["post_process"] = PostProcessNode(config=self.config)

    def get_output(self, state: AgentState) -> dict[str, Any]:
        output = {
            "output": state.get("formatted_output") or state.get("result", ""),
            "result": state.get("result", ""),
            "status": state.get("status", AgentStatus.ERROR.value),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "generation_mode": state.get("generation_mode"),
            "provider_error_message": state.get("provider_error_message"),
        }
        context = state.get("input_context")
        is_marketplace = isinstance(context, dict) and "conversation_history" in context
        if not is_marketplace:
            return output
        if _set_marketplace_guidance(output, state, "Resume-screening request"):
            return output
        payload = self._parse_payload(output.get("output", output.get("formatted_output")))
        if payload is not None:
            output["output"] = self._render_marketplace_shortlist(payload)
        return output

    @staticmethod
    def _parse_payload(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _render_marketplace_shortlist(payload: dict[str, Any]) -> str:
        summary = payload.get("ranking_summary")
        summary = summary if isinstance(summary, dict) else {}
        lines = [
            "# Resume Screening Shortlist",
            "",
            f"**Job:** {payload.get('job_id', 'unknown')}",
            f"**Candidates reviewed:** {summary.get('total', 0)}",
            f"**Passed mandatory gates:** {summary.get('passed_gates', 0)}",
            f"**Excluded:** {summary.get('excluded', 0)}",
        ]
        shortlist = payload.get("shortlist_top3")
        if isinstance(shortlist, list) and shortlist:
            lines.extend(["", "## Shortlisted candidates", ""])
            for index, candidate in enumerate(shortlist, start=1):
                if not isinstance(candidate, dict):
                    continue
                rank = candidate.get("rank", index)
                candidate_id = candidate.get("candidate_id", "Unknown candidate")
                score = candidate.get("aggregate_score")
                score_text = f" — score {score}" if score is not None else ""
                lines.append(f"{rank}. **{candidate_id}**{score_text}")
        else:
            lines.extend(["", "No candidates passed the mandatory screening gates."])
        lines.extend(["", "> This shortlist supports, but does not replace, human hiring review."])
        return "\n".join(lines)


def _set_marketplace_guidance(output: dict[str, Any], state: AgentState, subject: str) -> bool:
    context = state.get("input_context")
    message = state.get("input_error_message")
    if not (isinstance(context, dict) and "conversation_history" in context and message):
        return False
    lines = [f"{subject} could not be processed.", "", f"Reason: {message}"]
    guidance = state.get("input_error_guidance")
    if isinstance(guidance, list) and guidance:
        lines.extend(["", "How to continue:"])
        lines.extend(f"- {item}" for item in guidance)
    output["output"] = "\n".join(lines)
    return True
