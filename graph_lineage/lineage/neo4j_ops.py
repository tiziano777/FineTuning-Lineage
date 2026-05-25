"""Thin async wrapper functions for Neo4j operations used by the tracker.

All public functions are sync — they use asyncio.run() internally to call
the async Neo4j driver.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.neo4j_client.client import get_driver

logger = logging.getLogger(__name__)


async def _find_parent_experiment_async(uri: str) -> dict[str, Any] | None:
    """Query Neo4j for the most recent experiment with the given URI."""
    driver = await get_driver()
    query = """
    MATCH (e:Experiment {uri: $uri})
    RETURN e ORDER BY e.created_at DESC LIMIT 1
    """
    async with driver.session() as session:
        result = await session.run(query, {"uri": uri})
        record = await result.single()
        if record is None:
            return None
        return dict(record["e"])


def find_parent_experiment(uri: str) -> Experiment | None:
    """Find the most recent experiment for a given project URI.

    Args:
        uri: Project URI to search for.

    Returns:
        Experiment instance or None if no prior experiment exists.
    """
    data = asyncio.run(_find_parent_experiment_async(uri))
    if data is None:
        return None
    return Experiment.model_validate(data)


async def _find_experiment_by_id_async(experiment_id: str) -> dict[str, Any] | None:
    """Query Neo4j for an experiment by its unique ID."""
    driver = await get_driver()
    query = "MATCH (e:Experiment {id: $exp_id}) RETURN e LIMIT 1"
    async with driver.session() as session:
        result = await session.run(query, {"exp_id": experiment_id})
        record = await result.single()
        if record is None:
            return None
        return dict(record["e"])


def find_experiment_by_id(experiment_id: str) -> Experiment | None:
    """Find an experiment by its unique ID.

    Args:
        experiment_id: Experiment UUID to look up.

    Returns:
        Experiment instance or None if not found.
    """
    data = asyncio.run(_find_experiment_by_id_async(experiment_id))
    if data is None:
        return None
    return Experiment.model_validate(data)


async def _create_experiment_node_async(exp: Experiment) -> str:
    """Create an Experiment node in Neo4j."""
    driver = await get_driver()
    props = exp.model_dump(mode="python")
    # Convert datetime to ISO string for Neo4j
    for key in ("created_at", "updated_at"):
        if key in props and props[key] is not None:
            props[key] = props[key].isoformat()
    query = """
    CREATE (e:Experiment $props)
    RETURN e.id AS id
    """
    async with driver.session() as session:
        result = await session.run(query, {"props": props})
        record = await result.single()
        return record["id"]


def create_experiment_node(exp: Experiment) -> str:
    """Create an Experiment node in Neo4j and return its ID.

    Args:
        exp: Experiment instance to persist.

    Returns:
        The experiment ID.
    """
    return asyncio.run(_create_experiment_node_async(exp))


async def _create_edge_async(
    from_id: str,
    to_id: str,
    rel_type: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Create a relationship between two Experiment nodes."""
    driver = await get_driver()
    props_clause = ""
    params: dict[str, Any] = {"from_id": from_id, "to_id": to_id}
    if properties:
        props_clause = " $props"
        params["props"] = properties
    query = f"""
    MATCH (a:Experiment {{id: $from_id}})
    MATCH (b:Experiment {{id: $to_id}})
    CREATE (a)-[:{rel_type}{props_clause}]->(b)
    """
    async with driver.session() as session:
        await session.run(query, params)


def create_edge(
    from_id: str,
    to_id: str,
    rel_type: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Create a relationship between two Experiment nodes.

    Args:
        from_id: Source experiment ID.
        to_id: Target experiment ID.
        rel_type: Relationship type (DERIVED_FROM, RETRY_OF, STARTED_FROM).
        properties: Optional relationship properties.
    """
    asyncio.run(_create_edge_async(from_id, to_id, rel_type, properties))


async def _update_experiment_status_async(
    exp_id: str,
    status: str,
    exit_msg: str | None = None,
) -> None:
    """Update experiment status and optional exit message."""
    driver = await get_driver()
    query = """
    MATCH (e:Experiment {id: $exp_id})
    SET e.status = $status, e.exit_status = $status, e.updated_at = datetime()
    """
    params: dict[str, Any] = {"exp_id": exp_id, "status": status}
    if exit_msg is not None:
        query += ", e.exit_msg = $exit_msg"
        params["exit_msg"] = exit_msg
    async with driver.session() as session:
        await session.run(query, params)


def update_experiment_status(
    exp_id: str,
    status: str,
    exit_msg: str | None = None,
) -> None:
    """Update experiment status in Neo4j.

    Args:
        exp_id: Experiment ID to update.
        status: New status (COMPLETED, FAILED, etc.).
        exit_msg: Optional exit/error message.
    """
    asyncio.run(_update_experiment_status_async(exp_id, status, exit_msg))
