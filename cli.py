"""AGENTIC STAR Marketplace entrypoint for RET-C2-589."""

from shared.bootstrap.marketplace_app import run_agent_marketplace
from src.graph.graph import Graph

if __name__ == "__main__":
    run_agent_marketplace(Graph, agent_name="RET-C2-589", namespace="agent1000")
