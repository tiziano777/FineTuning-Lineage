"""Generic node/edge operations for lineage graph (endpoint /graph/nodes).

REFACTOR: Il payload viene serializzato in JSON string dal modello Pydantic
(EventNodeRequest.to_neo4j_params()) PRIMA di arrivare qui.
Questo modulo riceve solo parametri primitivi (str, int, float, bool, None).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import nest_asyncio

from graph_lineage.core.node_serializers import has_custom_serializer
from graph_lineage.neo4j_client.client import PersistentNeo4jClient

logger = logging.getLogger(__name__)

_nest_asyncio_applied = False
client = PersistentNeo4jClient(auto_init=True).get_instance()

_EDGE_TYPE_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_NODE_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _run_sync(coro) -> Any:
    """Run an async coroutine from sync context, compatible with existing event loops."""
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

async def _create_generic_graph_node_async(
    node_id: str,
    node_type: str,
    payload_json: str | None = None,
    **custom_props: Any,
) -> None:
    """Create a generic node in Neo4j with the correct label.

    REFACTOR: Riceve payload già serializzato in JSON string (o None per custom serializer).
    Tutti i parametri sono primitive Neo4j-safe.

    Args:
        node_id: UUID del nodo.
        node_type: Tipo/label del nodo.
        payload_json: JSON string del payload (ramo generico), o None (ramo custom).
        **custom_props: Proprietà flat per serializzatori custom (ramo Checkpoint, etc.)
    """
    if not _NODE_TYPE_PATTERN.match(node_type):
        raise ValueError(f"Invalid node_type '{node_type}': must match {_NODE_TYPE_PATTERN.pattern}")

    driver = await client.get_driver()
    async with driver.session() as session:
        if has_custom_serializer(node_type):
            # Ramo CUSTOM: usa custom_props (già flat e primitive dal serializzatore)
            # Esempio Checkpoint: custom_props = {name, epoch, uri, metrics, ...}
            all_props = {
                "id": node_id,
                "type": node_type,
                **custom_props,
            }
            props_lines = ",\n".join(f"    {k}: ${k}" for k in all_props.keys())
            query = f"""
                    CREATE (n:{node_type} {{{props_lines},
                        created_at: datetime()
                    }}) RETURN n
                    """
            params = all_props
            logger.debug("[CustomSerializer] %s query props: %s", node_type, list(all_props.keys()))
        else:
            # Ramo GENERICO: payload_json è una stringa JSON (Neo4j-safe)
            if payload_json is None:
                payload_json = json.dumps({})  # fallback vuoto

            query = f"""CREATE (n:{node_type} {{
    id: $node_id,
    type: $node_type,
    payload: $payload_json,
    created_at: datetime()
}}) RETURN n"""
            params = {"node_id": node_id, "node_type": node_type, "payload_json": payload_json}
            logger.debug("[GenericSerializer] %s, payload_json=%s", node_type, payload_json[:200])

        result = await session.run(query, **params)
        record = await result.single()
        await result.consume()

        if record:
            logger.info(
                "Node CREATED: id=%s, label=:%s, custom_serializer=%s",
                node_id, node_type, has_custom_serializer(node_type)
            )
        else:
            logger.warning("Node creation returned no record for id=%s", node_id)


async def _create_generic_edge_async(parent_id: str, child_id: str, edge_type: str) -> None:
    """Create a relationship from parent to child node."""
    normalized_edge_type = edge_type.upper()

    if not _EDGE_TYPE_PATTERN.match(normalized_edge_type):
        raise ValueError(
            f"Invalid edge_type '{edge_type}' (normalized: '{normalized_edge_type}'): "
            f"must match {_EDGE_TYPE_PATTERN.pattern}"
        )

    driver = await client.get_driver()
    async with driver.session() as session:
        query = f"""
        MATCH (parent {{id: $parent_id}})
        MATCH (child {{id: $child_id}})
        CREATE (parent)-[:{normalized_edge_type}]->(child)
        RETURN parent, child
        """
        result = await session.run(query, parent_id=parent_id, child_id=child_id)
        record = await result.single()
        await result.consume()

        if record:
            logger.info(
                "Edge CREATED: %s from %s to %s",
                normalized_edge_type, parent_id, child_id
            )
        else:
            logger.warning(
                "Edge creation returned no record: parent=%s, child=%s. "
                "Possible cause: parent node (run_id) does not exist.",
                parent_id, child_id
            )


# ── Public sync API ──────────────────────────────────────────────────────

def create_generic_graph_node(
    node_id: str,
    node_type: str,
    payload_json: str | None = None,
    **custom_props: Any,
) -> None:
    """Create a generic node in Neo4j (sync wrapper).

    Args:
        node_id: UUID del nodo.
        node_type: Tipo del nodo (Checkpoint, Metric, Artifact, ...).
        payload_json: JSON string del payload (solo ramo generico).
        **custom_props: Proprietà flat per serializzatori custom.
    """
    return _run_sync(_create_generic_graph_node_async(
        node_id=node_id,
        node_type=node_type,
        payload_json=payload_json,
        **custom_props,
    ))


def create_generic_edge(parent_id: str, child_id: str, edge_type: str) -> None:
    """Create a relationship from parent to child node (sync wrapper)."""
    return _run_sync(_create_generic_edge_async(parent_id, child_id, edge_type))