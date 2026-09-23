"""AgentCore Platform v1.0"""

# Service layer: domain queries, external API wrappers, data aggregation.
# Must NOT contain business logic, routing, or credentials.
# Nodes call this; this calls shared/services/ for external integrations.

from __future__ import annotations

from typing import Any


class Service:
    """Domain service."""

    async def fetch(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Not used in RET-C2-589. All domain logic is implemented directly in nodes.
        Retained as a scaffold placeholder for future extension."""
        return {}
