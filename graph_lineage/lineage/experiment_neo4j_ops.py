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
from graph_lineage.data_classes.neo4j.nodes.model import Model

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

# ── Experiment operations ─────────────────────────────────────────────────

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

def create_base_experiment_node_with_edges(
    exp: Experiment,
    recipe_name: str,
    component_name: str,
    model_name: str,
) -> str:
    """Create a base Experiment node and connect to Recipe, Component, Model in single atomic transaction.

    This ensures atomicity: if any resource doesn't exist or the connections fail,
    the experiment node is not created, preventing orphaned base experiments.

    Args:
        exp: The Experiment node to create (should have base=True).
        recipe_name: Name of the Recipe to connect via USES_RECIPE edge.
        component_name: Name of the Component to connect via USES_COMPONENT edge.
        model_name: Name of the Model to connect via USES_MODEL edge.

    Returns:
        The experiment ID.

    Raises:
        Exception: If any resource doesn't exist or database error occurs.
    """
    async def _create_base_experiment_node_with_edges_async(
        exp: Experiment,
        recipe_name: str,
        component_name: str,
        model_name: str,
    ) -> str:
        """Create base experiment with all resource edges in atomic transaction."""
        driver = await get_driver()
        props = exp.model_dump(mode="python")
        for key in ("created_at", "updated_at"):
            if key in props and props[key] is not None:
                props[key] = props[key].isoformat()

        labels_str = ":".join(exp.__labels__)
        props.pop("base", None)
        props.pop("experiment_type", None)

        # Atomic transaction: create node + all resource edges
        query = f"""
        MATCH (r:Recipe {{name: $recipe_name}})
        MATCH (c:Component {{name: $component_name}})
        MATCH (m:Model {{model_name: $model_name}})
        CREATE (e:{labels_str} $exp_props)
        CREATE (e)-[:USES_RECIPE]->(r)
        CREATE (e)-[:USES_COMPONENT]->(c)
        CREATE (e)-[:USES_MODEL]->(m)
        RETURN e.id AS id
        """

        params: dict[str, Any] = {
            "exp_props": props,
            "recipe_name": recipe_name,
            "component_name": component_name,
            "model_name": model_name,
        }

        async with driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            if record is None:
                raise ValueError(
                    f"Failed to create base experiment: Recipe='{recipe_name}', "
                    f"Component='{component_name}', Model='{model_name}' not found"
                )
            return record["id"]

    return _run_sync(_create_base_experiment_node_with_edges_async(
        exp, recipe_name, component_name, model_name
    ))

def create_non_base_experiment_with_chain_edge(
    exp: Experiment,
    parent_exp_id: str,
    strategy: str,
    edge_properties: dict[str, Any] | None = None,
    parent_ckp_uri: str | None = None,
) -> str:
    """Create a non-base Experiment node and connect it to its parent in a single atomic transaction.

    This ensures atomicity: if the parent doesn't exist or the connection fails,
    the experiment node is not created, preventing orphaned experiments.

    Args:
        exp: The Experiment node to create (should have base=False).
        parent_exp_id: ID of the parent experiment (must exist).
        strategy: Edge type (DERIVED_FROM, RETRY_FROM, RESUMED_FROM, MERGED_FROM).
        edge_properties: Optional properties for the Experiment→Experiment edge.
        parent_ckp_uri: Optional checkpoint URI to create CKP_RESUMED_FROM edge (for RESUME strategy).

    Returns:
        The experiment ID.

    Raises:
        Exception: If parent experiment doesn't exist or database error occurs.
    """
    async def _create_non_base_experiment_with_chain_edge_async(
        exp: Experiment,
        parent_exp_id: str,
        strategy: str,
        edge_properties: dict[str, Any] | None = None,
        parent_ckp_uri: str | None = None,
    ) -> str:
        """Create non-base experiment with parent edge in atomic transaction."""
        driver = await get_driver()
        props = exp.model_dump(mode="python")
        for key in ("created_at", "updated_at"):
            if key in props and props[key] is not None:
                props[key] = props[key].isoformat()

        labels_str = ":".join(exp.__labels__)
        props.pop("base", None)
        props.pop("experiment_type", None)

        # Build atomic transaction: create node + parent edge + optional checkpoint edge
        query = f"""
        MATCH (parent:Experiment {{id: $parent_exp_id}})
        CREATE (e:{labels_str} $exp_props)
        CREATE (e)-[:{strategy} $edge_props]->(parent)
        """

        params: dict[str, Any] = {
            "exp_props": props,
            "parent_exp_id": parent_exp_id,
            "edge_props": edge_properties or {},
        }

        # Optional: create checkpoint edge for RESUME strategy
        if parent_ckp_uri:
            query += """
        OPTIONAL MATCH (ckp:Checkpoint {uri: $ckp_uri})
        CREATE (e)-[:CKP_RESUMED_FROM]->(ckp)
        """
            params["ckp_uri"] = parent_ckp_uri

        query += "\nRETURN e.id AS id"

        async with driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            if record is None:
                raise ValueError(f"Failed to create experiment with parent_exp_id={parent_exp_id}")
            return record["id"]

    return _run_sync(_create_non_base_experiment_with_chain_edge_async(
        exp, parent_exp_id, strategy, edge_properties, parent_ckp_uri
    ))

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

def create_base_experiment_edge(exp_id: str, recipe_name: str, component_name: str, model_name: str) -> None:
    """Create BASE_EXPERIMENT relationship from Experiment to Recipe, Component, and Model."""
    async def _create_base_experiment_edge_async(exp_name: str, recipe_name: str, component_name: str, model_name: str) -> None:
        driver = await get_driver()
        query = """
        MATCH (e:Experiment {id: $exp_id})
        MATCH (r:Recipe {name: $recipe_name})
        MATCH (c:Component {name: $component_name})
        MATCH (m:Model {model_name: $model_name})
        CREATE (e)-[:USES_RECIPE]->(r)
        CREATE (e)-[:USES_COMPONENT]->(c)
        CREATE (e)-[:USES_MODEL]->(m)
        """
        async with driver.session() as session:
            await session.run(query, {"exp_id": exp_id, "recipe_name": recipe_name, "component_name": component_name, "model_name": model_name})

    _run_sync(_create_base_experiment_edge_async(exp_id, recipe_name, component_name, model_name))

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

# ── Model operations ─────────────────────────────────────────────────────

def find_model_by_name(model_name: str) -> Model | None:
    """Find a model node by its name."""
    async def _find_model_by_name_async(model_name: str) -> Model | None:
        """Query Neo4j for a model node by its name."""
        driver = await get_driver()
        query = "MATCH (m:Model {model_name: $model_name}) RETURN m LIMIT 1"
        async with driver.session() as session:
            result = await session.run(query, {"model_name": model_name})
            record = await result.single()
            if record is None:
                return None
            return Model.model_validate(record["m"])

    data = _run_sync(_find_model_by_name_async(model_name))
    if data is None:
        return None
    return data

