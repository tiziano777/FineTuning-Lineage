"""Thin async wrapper functions for Neo4j operations used by the tracker.

All public functions are sync — they detect the event loop state and
use the appropriate strategy:
- No running loop: asyncio.run() (standard)
- Running loop (Jupyter, Streamlit, FastAPI): nest_asyncio + run_until_complete
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import nest_asyncio

from graph_lineage.data_classes.neo4j.nodes.checkpoint import Checkpoint
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.neo4j_client.client import get_driver

logger = logging.getLogger(__name__)

_nest_asyncio_applied = False


def _run_sync(coro) -> Any:
    """Run an async coroutine from sync context, compatible with existing event loops.

    If an event loop is already running (Jupyter, Streamlit, FastAPI),
    patches it with nest_asyncio and uses run_until_complete.
    Otherwise, uses standard asyncio.run().
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
    """Find the most recent experiment for a given project URI."""
    if not uri:
        return None
    data = _run_sync(_find_parent_experiment_async(uri))
    if data is None:
        return None
    return Experiment.model_validate(data)

async def _find_parent_experiment_id_async(experiment_id: str) -> str | None:
    """
    Trova l'ID del parent di un esperimento attraverso le relazioni DERIVED_FROM o RETRY_FROM.
    """
    driver = await get_driver()
    query = """
    MATCH (e:Experiment {id: $id})-[r:DERIVED_FROM|RETRY_FROM]->(parent:Experiment)
    RETURN parent.id AS parent_id
    """
    async with driver.session() as session:
        result = await session.run(query, {"id": experiment_id})
        record = await result.single()
        if record is None:
            return None
        return record["parent_id"]

async def _find_experiment_by_id_async(experiment_id: str) -> Experiment | None:
    """Query Neo4j for an experiment by its unique ID."""
    driver = await get_driver()
    query = "MATCH (e:Experiment {id: $exp_id}) RETURN e LIMIT 1"
    async with driver.session() as session:
        result = await session.run(query, {"exp_id": experiment_id})
        record = await result.single()
        if record is None:
            return None
        return Experiment.model_validate(record["e"])


def find_experiment_by_id(experiment_id: str) -> Experiment | None:
    """Find an experiment by its unique ID."""
    data = _run_sync(_find_experiment_by_id_async(experiment_id))
    if data is None:
        return None
    return Experiment.model_validate(data)


async def _create_experiment_node_async(exp: Experiment) -> str:
    """Create an Experiment node in Neo4j."""
    driver = await get_driver()
    props = exp.model_dump(mode="python")
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
    """Create an Experiment node in Neo4j and return its ID."""
    return _run_sync(_create_experiment_node_async(exp))


async def _create_experiment_edge_async(
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
        rel_type: Relationship type (DERIVED_FROM, RETRY_FROM, DERIVED_FROM).
        properties: Optional relationship properties.
    """
    _run_sync(_create_experiment_edge_async(from_id, to_id, rel_type, properties))


async def _create_started_from_edge_async(exp_id: str, ckp_id: str) -> None:
    """Create STARTED_FROM relationship from Experiment to Checkpoint."""
    driver = await get_driver()
    query = """
    MATCH (e:Experiment {id: $exp_id})
    MATCH (c:Checkpoint {id: $ckp_id})
    CREATE (e)-[:STARTED_FROM]->(c)
    """
    async with driver.session() as session:
        await session.run(query, {"exp_id": exp_id, "ckp_id": ckp_id})


def create_started_from_edge(exp_id: str, ckp_id: str) -> None:
    """Create STARTED_FROM relationship from Experiment to Checkpoint.

    Used for RESUME and BRANCH-with-checkpoint strategies where the new
    experiment physically starts from a specific checkpoint's weights.

    Args:
        exp_id: Source experiment ID.
        ckp_id: Target checkpoint ID (the one weights are loaded from).
    """
    _run_sync(_create_started_from_edge_async(exp_id, ckp_id))


async def _update_experiment_status_async(
    exp_id: str,
    status: str,
    exit_msg: str | None = None,
    metrics_uri: str | None = None,
) -> None:
    """Update experiment status and optional exit message."""
    driver = await get_driver()
    query = """
    MATCH (e:Experiment {id: $exp_id})
    SET e.status = $status, e.exit_status = $status, e.updated_at = datetime(), e.metrics_uri = $metrics_uri
    """
    params: dict[str, Any] = {"exp_id": exp_id, "status": status, "metrics_uri": metrics_uri}
    if exit_msg is not None:
        query += ", e.exit_msg = $exit_msg"
        params["exit_msg"] = exit_msg
    async with driver.session() as session:
        await session.run(query, params)


def update_experiment_status(
    exp_id: str,
    status: str,
    exit_msg: str | None = None,
    metrics_uri: str | None = None,
) -> None:
    """Update experiment status in Neo4j."""
    _run_sync(_update_experiment_status_async(exp_id, status, exit_msg, metrics_uri))


# ── Checkpoint operations ─────────────────────────────────────────────────────


async def _create_checkpoint_node_async(ckp: Checkpoint) -> str:
    """Create a Checkpoint node in Neo4j."""
    driver = await get_driver()
    props = ckp.model_dump(mode="python")
    for key in ("created_at", "updated_at"):
        if key in props and props[key] is not None:
            props[key] = props[key].isoformat()
    query = """
    CREATE (c:Checkpoint $props)
    RETURN c.id AS id
    """
    async with driver.session() as session:
        result = await session.run(query, {"props": props})
        record = await result.single()
        return record["id"]


def create_checkpoint_node(ckp: Checkpoint) -> str:
    """Create a Checkpoint node in Neo4j and return its ID."""
    return _run_sync(_create_checkpoint_node_async(ckp))


async def _create_checkpoint_edge_async(exp_id: str, ckp_id: str) -> None:
    """Create PRODUCED relationship from Experiment to Checkpoint."""
    driver = await get_driver()
    query = """
    MATCH (e:Experiment {id: $exp_id})
    MATCH (c:Checkpoint {id: $ckp_id})
    CREATE (e)-[:PRODUCED]->(c)
    """
    async with driver.session() as session:
        await session.run(query, {"exp_id": exp_id, "ckp_id": ckp_id})


def create_checkpoint_edge(exp_id: str, ckp_id: str) -> None:
    """Create PRODUCED relationship from Experiment to Checkpoint."""
    _run_sync(_create_checkpoint_edge_async(exp_id, ckp_id))