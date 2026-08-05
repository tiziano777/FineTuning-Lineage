"""Generic node/edge operations for lineage graph (endpoint /graph/nodes).

REFACTOR: The payload is serialized to JSON string by the Pydantic model
(EventNodeRequest.to_neo4j_params()) BEFORE arriving here.
This module receives only primitive parameters (str, int, float, bool, None).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
import nest_asyncio
from graph_lineage.neo4j_client.client import PersistentNeo4jClient

logger = logging.getLogger(__name__)

class GenericEventRepository:
    """Handles generic node/edge operations for the lineage graph."""
    
    _nest_asyncio_applied = False
    _client = PersistentNeo4jClient(auto_init=True).get_instance()
    
    _EDGE_TYPE_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
    _NODE_TYPE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    
    @classmethod
    def _run_sync(cls, coro) -> Any:
        """Run an async coroutine from sync context, compatible with existing event loops."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            if not cls._nest_asyncio_applied:
                nest_asyncio.apply()
                cls._nest_asyncio_applied = True
            return loop.run_until_complete(coro)
        else:
            return asyncio.run(coro)
    
    # ── Async internals (private) ─────────────────────────────────────────────
    
    @classmethod
    async def _create_generic_graph_node_async(
        cls,
        node_id: str,
        node_type: str,
        payload_json: str | None = None,
        **custom_props: Any,
    ) -> None:
        """Create a generic node in Neo4j with the correct label.

        REFACTOR: Receives payload already serialized as JSON string (or None for custom serializer).
        All parameters are Neo4j-safe primitives.

        Args:
            node_id: UUID of the node.
            node_type: Type/label of the node.
            payload_json: JSON string of the payload (generic branch), or None (custom branch).
            **custom_props: Flat properties for custom serializers (Checkpoint branch, etc.)
        """
        if not cls._NODE_TYPE_PATTERN.match(node_type):
            raise ValueError(f"Invalid node_type '{node_type}': must match {cls._NODE_TYPE_PATTERN.pattern}")

        driver = await cls._client.get_driver()
        async with driver.session() as session:
            # CUSTOM branch: uses custom_props (already flat and primitive from serializer)
            # Example Checkpoint: custom_props = {name, epoch, uri, metrics, ...}
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
                logger.info("Node CREATED: %s", node_type)
            else:
                logger.warning("Node creation returned no record for id=%s", node_id)
    
    @classmethod
    async def _create_generic_edge_async(cls, parent_id: str, child_id: str, edge_type: str) -> None:
        """Create a relationship from parent to child node."""
        normalized_edge_type = edge_type.upper()

        if not cls._EDGE_TYPE_PATTERN.match(normalized_edge_type):
            raise ValueError(
                f"Invalid edge_type '{edge_type}' (normalized: '{normalized_edge_type}'): "
                f"must match {cls._EDGE_TYPE_PATTERN.pattern}"
            )

        driver = await cls._client.get_driver()
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
    
    @classmethod
    def create_generic_graph_node(
        cls,
        node_id: str,
        node_type: str,
        payload_json: str | None = None,
        **custom_props: Any,
    ) -> None:
        """Create a generic node in Neo4j (sync wrapper).

        Args:
            node_id: UUID of the node.
            node_type: Type of the node (Checkpoint, Metric, Artifact, ...).
            payload_json: JSON string of the payload (generic branch only).
            **custom_props: Flat properties for custom serializers.
        """
        return cls._run_sync(cls._create_generic_graph_node_async(
            node_id=node_id,
            node_type=node_type,
            payload_json=payload_json,
            **custom_props,
        ))
    
    @classmethod
    def create_generic_edge(cls, parent_id: str, child_id: str, edge_type: str) -> None:
        """Create a relationship from parent to child node (sync wrapper)."""
        return cls._run_sync(cls._create_generic_edge_async(parent_id, child_id, edge_type))

