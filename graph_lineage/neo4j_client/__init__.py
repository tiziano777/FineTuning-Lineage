"""Neo4j data layer for lineage tracking system."""

from __future__ import annotations

from graph_lineage.neo4j_client.client import close_driver, get_driver

__all__ = [
    "get_driver",
    "close_driver",
]
