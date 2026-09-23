"""Unit tests for Graph node registration (replaces placeholder test_main_node.py)."""

from __future__ import annotations

import pytest

pytest.importorskip("framework")

from src.graph.graph import Graph


def test_graph_registers_three_domain_slots():
    graph = Graph(config={})
    graph.compile()
    assert "pre_process" in graph._nodes
    assert "main" in graph._nodes
    assert "post_process" in graph._nodes


def test_graph_name_is_correct():
    graph = Graph(config={})
    assert graph.name == "ret_c2_589"


def test_graph_node_count_at_least_five():
    # initialize + pre_process + main + post_process + finalize
    graph = Graph(config={})
    graph.compile()
    assert len(graph._nodes) >= 5


def test_main_graph_node_receives_injected_llm_identity():
    sentinel = object()
    graph = Graph(config={"llm": sentinel})
    graph.compile()
    main = graph._nodes["main"]
    assert main._llm is sentinel
    assert main.get_subgraph()._nodes["resume_parse"]._llm is sentinel


def test_domain_workflow_graph_registers_three_nodes():
    from src.graph.domain_workflow_graph import DomainWorkflowGraph
    graph = DomainWorkflowGraph(config={})
    graph.compile()
    assert "resume_parse" in graph._nodes
    assert "criteria_score" in graph._nodes
    assert "ranking" in graph._nodes
