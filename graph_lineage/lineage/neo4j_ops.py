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
import traceback

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


def find_experiment_by_id(experiment_id: str) -> Experiment | None:
    """Find an experiment by its unique ID."""
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

    data = _run_sync(_find_experiment_by_id_async(experiment_id))
    if data is None:
        return None
    return Experiment.model_validate(data)

def find_parent_experiment_id(experiment_id: str) -> str | None:
    """Find the parent experiment ID of a given experiment."""
    async def _find_parent_experiment_id_async(experiment_id: str) -> str | None:
        """Query Neo4j for the parent experiment ID."""
        driver = await get_driver()
        query = """
        MATCH (child:Experiment {id: $exp_id})-[:DERIVED_FROM|RETRY_FROM|RESUMED_FROM]->(parent:Experiment)
        RETURN parent.id AS parent_id
        LIMIT 1
        """
        async with driver.session() as session:
            result = await session.run(query, {"exp_id": experiment_id})
            record = await result.single()
            if record is None:
                return None
            return record["parent_id"]

    return _run_sync(_find_parent_experiment_id_async(experiment_id))

def create_experiment_node(exp: Experiment) -> str:
    """Create an Experiment node in Neo4j and return its ID."""
    async def _create_experiment_node_async(exp: Experiment) -> str:
        """Create an Experiment node in Neo4j."""
        driver = await get_driver()
        props = exp.model_dump(mode="python")
        for key in ("created_at", "updated_at"):
            if key in props and props[key] is not None:
                props[key] = props[key].isoformat()
        # 1. Generiamo la stringa delle etichette (es: "Experiment:Training" o "Experiment:Evaluation")
        # Usiamo exp.__labels__ che abbiamo definito nel modello Pydantic
        labels_str = ":".join(exp.__labels__)
        
        # 2. Iniettiamo le label usando la f-string (sicuro, perché le label sono controllate dal tuo codice)
        # Il resto delle proprietà ($props) rimane parametrizzato per evitare Cypher Injection
        query = f"""
        CREATE (e:{labels_str} $props)
        RETURN e.id AS id
        """
        async with driver.session() as session:
            result = await session.run(query, {"props": props})
            record = await result.single()
            return record["id"]

    return _run_sync(_create_experiment_node_async(exp))

def create_experiment_edge(from_id: str, to_id: str, rel_type: str, properties: dict[str, Any] | None = None,
) -> None:
    """Create a relationship between two Experiment nodes.

    Args:
        from_id: Source experiment ID.
        to_id: Target experiment ID.
        rel_type: Relationship type (DERIVED_FROM, RETRY_FROM, DERIVED_FROM).
        properties: Optional relationship properties.
    """
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

    _run_sync(_create_experiment_edge_async(from_id, to_id, rel_type, properties))

def create_resumed_from_edge(exp_id: str, ckp_uri: str) -> None:
    """Create CKP_RESUMED_FROM relationship from Experiment to Checkpoint.

    Used for RESUME strategies where the new
    experiment physically starts from a specific checkpoint's weights.

    Args:
        exp_id: Source experiment ID.
        ckp_uri: Target checkpoint URI (the one weights are loaded from).
    """
    async def _create_resumed_from_edge_async(exp_id: str, ckp_uri: str) -> None:
        """Create RESUMED_FROM relationship from Experiment to Checkpoint."""
        driver = await get_driver()
        query = """
        MATCH (e:Experiment {id: $exp_id})
        MATCH (c:Checkpoint {uri: $ckp_uri})
        CREATE (e)-[:CKP_RESUMED_FROM]->(c)
        """
        async with driver.session() as session:
            await session.run(query, {"exp_id": exp_id, "ckp_uri": ckp_uri})

    _run_sync(_create_resumed_from_edge_async(exp_id, ckp_uri))

def update_experiment_status(exp_id: str, status: str, exit_msg: str | None = None, metrics_uri: str | None = None) -> None:
    """Update experiment status in Neo4j."""

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

    _run_sync(_update_experiment_status_async(exp_id, status, exit_msg, metrics_uri))

# ── Checkpoint operations ─────────────────────────────────────────────────────

def create_checkpoint_node(ckp: Checkpoint) -> str:
    """Create a Checkpoint node in Neo4j and return its ID."""
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

    return _run_sync(_create_checkpoint_node_async(ckp))

def create_checkpoint_edge(exp_id: str, ckp_id: str) -> None:
    """Create PRODUCED relationship from Experiment to Checkpoint."""
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

    _run_sync(_create_checkpoint_edge_async(exp_id, ckp_id))

def create_ckp_derived_from_edge(base_ckp_id: str, new_ckp_id: str) -> None:
    """Create CKP_DERIVED_FROM relationship between Checkpoints.
    Used when a new checkpoint is derived from an existing one (e.g., during RESUME).
    Args:
        base_ckp_id: ID of the base checkpoint.
        new_ckp_id: ID of the new checkpoint derived from the base.
    """
    async def _create_ckp_derived_from_edge_async(base_ckp_id: str, new_ckp_id: str) -> None:
        """Create CKP_DERIVED_FROM relationship between Checkpoints."""
        driver = await get_driver()
        query = """
        MATCH (base:Checkpoint {id: $base_ckp_id})
        MATCH (new:Checkpoint {id: $new_ckp_id})
        CREATE (new)-[:CKP_DERIVED_FROM]->(base)
        """
        async with driver.session() as session:
            await session.run(query, {"base_ckp_id": base_ckp_id, "new_ckp_id": new_ckp_id})

    _run_sync(_create_ckp_derived_from_edge_async(base_ckp_id, new_ckp_id))

def retrieve_ckp_by_experiment_id(exp_id: str) -> list[Checkpoint]:
    """Retrieve all Checkpoints produced by a given Experiment."""
    driver = _run_sync(get_driver())
    query = """
    MATCH (e:Experiment {id: $exp_id})-[:PRODUCED]->(c:Checkpoint)
    RETURN c
    """
    async def _retrieve_ckp_async() -> list[Checkpoint]:
        async with driver.session() as session:
            result = await session.run(query, {"exp_id": exp_id})
            records = await result.data()  # Restituisce lista di dict
            return [Checkpoint.model_validate(record["c"]) for record in records]
    return _run_sync(_retrieve_ckp_async())

def retrieve_ckp_id_by_ckp_uri(ckp_uri: str) -> str:
    """Retrieve the Checkpoint ID that matches a given checkpoint URI."""
    driver = _run_sync(get_driver())
    query = """
    MATCH (c:Checkpoint {uri: $ckp_uri})
    RETURN c.id AS id
    LIMIT 1
    """
    async def _retrieve_ckp_id_async() -> str:
        async with driver.session() as session:
            result = await session.run(query, {"ckp_uri": ckp_uri})
            record = await result.single()
            return record["id"]
    return _run_sync(_retrieve_ckp_id_async())

def find_experiment_from_chain(base_exp_id: str, ckp_uri: str) -> Experiment:
    """Find the experiment that produced a checkpoint with the given URI, starting from a base experiment.

    Args:
        base_exp_id: The ID of the base experiment to start the search from.
        ckp_uri: The URI of the checkpoint to find.

    Returns:
        The Experiment that produced the checkpoint with the given URI.

    Raises:
        ValueError: If no experiment is found that produced the checkpoint with the given URI.
    """
    driver = _run_sync(get_driver())
    query = """
    MATCH (base:Experiment {id: $base_exp_id})<-[:RESUMED_FROM|RETRY_FROM|DERIVED_FROM*0..]-(e:Experiment)-[:PRODUCED]->(c:Checkpoint {uri: $ckp_uri})
    RETURN e
    LIMIT 1
    """
    async def _find_experiment_from_chain_async() -> Experiment:
        async with driver.session() as session:
            result = await session.run(query, {"base_exp_id": base_exp_id, "ckp_uri": ckp_uri})
            record = await result.single()
            if record is None:
                raise ValueError(f"No experiment found that produced checkpoint with URI '{ckp_uri}' starting from base experiment '{base_exp_id}'.\n{traceback.format_exc()}")
            return Experiment.model_validate(record["e"])
    
    return _run_sync(_find_experiment_from_chain_async())

