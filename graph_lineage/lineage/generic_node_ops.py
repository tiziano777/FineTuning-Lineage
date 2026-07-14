"""Generic node/edge operations for lineage graph (endpoint /graph/nodes).

Allineato al pattern di neo4j_ops.py: funzioni pubbliche SINCRONE che wrappano
logica async via _run_sync() + nest_asyncio.

Supporta logica custom per tipi specifici (es. Checkpoint) mantenendo
l'interfaccia generica per tutti gli altri tipi.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import nest_asyncio

from graph_lineage.neo4j_client.client import get_driver

logger = logging.getLogger(__name__)

_nest_asyncio_applied = False

_EDGE_TYPE_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_NODE_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

def _run_sync(coro) -> Any:
    """Run an async coroutine from sync context, compatible with existing event loops.

    Copia 1:1 dal pattern di neo4j_ops.py.
    """
    global _nest_asyncio_applied

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        if not _nest_asyncio_applied:
            nest_asyncio.apply()
            _nest_asyncio_applied = True
        return loop.run_until_complete(coro)
    else:
        return asyncio.run(coro)

# ── Async internals (private) ─────────────────────────────────────────────

async def _create_generic_graph_node_async(node_id: str, node_type: str, payload: dict[str, Any]) -> None:
    """Create a generic node in Neo4j with the correct label.

    Per tipi con logica custom (es. Checkpoint), le proprietà vengono
    flatten direttamente sul nodo invece di essere nested in `payload`.
    """
    if not _NODE_TYPE_PATTERN.match(node_type):
        raise ValueError(f"Invalid node_type '{node_type}': must match {_NODE_TYPE_PATTERN.pattern}")

    driver = await get_driver()
    async with driver.session() as session:
        # Logica custom per Checkpoint: proprietà flat + label specifica
        if node_type == "Checkpoint":
            query = """
            CREATE (n:Checkpoint {
                id: $node_id,
                type: $node_type,
                name: $name,
                derived_from: $derived_from,
                epoch: $epoch,
                run: $run,
                uri: $uri,
                metrics: $metrics,
                is_merging: $is_merging,
                created_at: datetime()
            })
            RETURN n
            """
            await session.run(
                query,
                node_id=node_id,
                node_type=node_type,
                name=payload.get("name", ""),
                derived_from=payload.get("derived_from", ""),
                epoch=payload.get("epoch", 0),
                run=payload.get("run", 0),
                uri=payload.get("uri", ""),
                metrics=payload.get("metrics", ""),
                is_merging=payload.get("is_merging", False),
            )
        else:
            # Generico: tutto nel campo payload
            query = f"""
            CREATE (n:{node_type} {{
                id: $node_id,
                type: $node_type,
                payload: $payload,
                created_at: datetime()
            }})
            RETURN n
            """
            await session.run(
                query,
                node_id=node_id,
                node_type=node_type,
                payload=payload,
            )
        logger.debug("Created node %s with label :%s", node_id, node_type)

async def _create_generic_edge_async(parent_id: str, child_id: str, edge_type: str) -> None:
    """Create a relationship from parent to child node."""
    if not _EDGE_TYPE_PATTERN.match(edge_type):
        raise ValueError(f"Invalid edge_type '{edge_type}': must match {_EDGE_TYPE_PATTERN.pattern}")

    driver = await get_driver()
    async with driver.session() as session:
        query = f"""
        MATCH (parent {{id: $parent_id}})
        MATCH (child {{id: $child_id}})
        CREATE (parent)-[:{edge_type}]->(child)
        """
        await session.run(query, parent_id=parent_id, child_id=child_id)
        logger.debug("Created edge %s from %s to %s", edge_type, parent_id, child_id)

# ── Public sync API (usata da FastAPI e neo4j_ops) ──────────────────────

def create_generic_graph_node(node_id: str, node_type: str, payload: dict[str, Any]) -> None:
    """Create a generic node in Neo4j (sync wrapper).

    Args:
        node_id: UUID del nodo.
        node_type: Tipo del nodo (Checkpoint, Metric, Artifact, ...).
                   Determina la label Neo4j (:{node_type}).
        payload: Dati del nodo. Per Checkpoint, le chiavi vengono flatten
                 come proprietà dirette del nodo.
    """
    return _run_sync(_create_generic_graph_node_async(node_id, node_type, payload))

def create_generic_edge(parent_id: str, child_id: str, edge_type: str) -> None:
    """Create a relationship from parent to child node (sync wrapper).

    Args:
        parent_id: ID del nodo parent (es. Experiment run_id).
        child_id: ID del nodo child.
        edge_type: Tipo di relazione (PRODUCED, DERIVED_FROM, ...).
    """
    return _run_sync(_create_generic_edge_async(parent_id, child_id, edge_type))
