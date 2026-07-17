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

from graph_lineage.data_classes.neo4j.nodes.code.training.checkpoint import Checkpoint
from graph_lineage.data_classes.neo4j.nodes.code.training.experiment import Experiment
from graph_lineage.data_classes.neo4j.nodes.code.training.model import Model
from graph_lineage.neo4j_client.client import PersistentNeo4jClient

logger = logging.getLogger(__name__)
_nest_asyncio_applied = False
client = PersistentNeo4jClient(auto_init=True).get_instance()

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

# ── Experiment operations ─────────────────────────────────────────────────

def find_experiment_by_id(experiment_id: str) -> Experiment | None:
    """Find an experiment by its unique ID."""
    async def _async(experiment_id: str) -> Experiment | None:
        driver = await client.get_driver()
        query = "MATCH (e:Experiment {id: $exp_id}) RETURN e LIMIT 1"
        async with driver.session() as session:
            result = await session.run(query, {"exp_id": experiment_id})
            record = await result.single()
            if record is None:
                return None
            return Experiment.model_validate(record["e"])

    data = _run_sync(_async(experiment_id))
    if data is None:
        return None
    return Experiment.model_validate(data)

def find_parent_experiment_id(experiment_id: str) -> str | None:
    """Find the parent experiment ID of a given experiment."""
    async def _async(experiment_id: str) -> str | None:
        driver = await client.get_driver()
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

    return _run_sync(_async(experiment_id))

def create_base_experiment_node_with_edges(
    exp: Experiment,
    recipe_name: str,
    component_name: str,
    model_name: str,
    resumed_from: str | None = None,
) -> str:
    """Create a base Experiment node and connect to Recipe, Component, Model atomically.

    REFACTOR: supports resumed_from for model-switch base experiments.
    """
    async def _async(
        exp: Experiment,
        recipe_name: str,
        component_name: str,
        model_name: str,
        resumed_from: str | None = None,
    ) -> str:
        driver = await client.get_driver()
        props = exp.model_dump(mode="python")
        for key in ("created_at", "updated_at"):
            if key in props and props[key] is not None:
                props[key] = props[key].isoformat()

        labels_str = ":".join(exp.__labels__)
        props.pop("base", None)
        props.pop("experiment_type", None)

        if resumed_from is not None:
            props["resumed_from"] = resumed_from

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

    return _run_sync(_async(exp, recipe_name, component_name, model_name, resumed_from))

def create_non_base_experiment_with_chain_edge(
    exp: Experiment,
    parent_exp_id: str,
    strategy: str,
    edge_properties: dict[str, Any] | None = None,
) -> str:
    """Create a non-base Experiment node and connect it to its parent atomically.

    REFACTOR: removed all CKP_RESUMED_FROM logic. CKP-Experiment bridges are gone.
    """
    async def _async(
        exp: Experiment,
        parent_exp_id: str,
        strategy: str,
        edge_properties: dict[str, Any] | None = None,
    ) -> str:
        driver = await client.get_driver()
        props = exp.model_dump(mode="python")
        for key in ("created_at", "updated_at"):
            if key in props and props[key] is not None:
                props[key] = props[key].isoformat()

        labels_str = ":".join(exp.__labels__)
        props.pop("base", None)
        props.pop("experiment_type", None)

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

        query += "\nRETURN e.id AS id"

        async with driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            if record is None:
                raise ValueError(f"Failed to create experiment with parent_exp_id={parent_exp_id}")
            return record["id"]

    return _run_sync(_async(exp, parent_exp_id, strategy, edge_properties))

def update_experiment_status(
    exp_id: str,
    status: str,
    exit_msg: str | None = None,
    metrics_uri: str | None = None,
) -> None:
    """Update experiment status in Neo4j."""
    async def _async(
        exp_id: str, status: str, exit_msg: str | None, metrics_uri: str | None
    ) -> None:
        driver = await client.get_driver()
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

    _run_sync(_async(exp_id, status, exit_msg, metrics_uri))

# ── Checkpoint operations ─────────────────────────────────────────────────

def retrieve_ckp_by_experiment_id(exp_id: str) -> list[Checkpoint]:
    """Retrieve all Checkpoints produced by a given Experiment."""
    driver = _run_sync(client.get_driver())
    query = """
    MATCH (e:Experiment {id: $exp_id})-[:PRODUCED]->(c:Checkpoint)
    RETURN c
    """
    async def _async() -> list[Checkpoint]:
        async with driver.session() as session:
            result = await session.run(query, {"exp_id": exp_id})
            records = await result.data()
            return [Checkpoint.model_validate(record["c"]) for record in records]
    return _run_sync(_async())

def retrieve_ckp_id_by_ckp_uri(ckp_uri: str) -> str:
    """Retrieve the Checkpoint ID that matches a given checkpoint URI."""
    driver = _run_sync(client.get_driver())
    query = """
    MATCH (c:Checkpoint {uri: $ckp_uri})
    RETURN c.id AS id
    LIMIT 1
    """
    async def _async() -> str:
        async with driver.session() as session:
            result = await session.run(query, {"ckp_uri": ckp_uri})
            record = await result.single()
            return record["id"]
    return _run_sync(_async())

def find_experiment_from_chain(base_exp_id: str, ckp_uri: str) -> Experiment:
    """Find the experiment that produced a checkpoint with the given URI."""
    driver = _run_sync(client.get_driver())
    query = """
    MATCH (base:Experiment {id: $base_exp_id})<-[:RESUMED_FROM|RETRY_FROM|DERIVED_FROM*0..]-(e:Experiment)-[:PRODUCED]->(c:Checkpoint {uri: $ckp_uri})
    RETURN e
    LIMIT 1
    """
    async def _async() -> Experiment:
        async with driver.session() as session:
            result = await session.run(query, {"base_exp_id": base_exp_id, "ckp_uri": ckp_uri})
            record = await result.single()
            if record is None:
                raise ValueError(
                    f"No experiment found that produced checkpoint with URI '{ckp_uri}' "
                    f"starting from base experiment '{base_exp_id}'.\n{traceback.format_exc()}"
                )
            return Experiment.model_validate(record["e"])

    return _run_sync(_async())

# ── Model operations ─────────────────────────────────────────────────────

def find_model_by_name(model_name: str) -> Model | None:
    """Find a model node by its name."""
    async def _async(model_name: str) -> Model | None:
        driver = await client.get_driver()
        query = "MATCH (m:Model {model_name: $model_name}) RETURN m LIMIT 1"
        async with driver.session() as session:
            result = await session.run(query, {"model_name": model_name})
            record = await result.single()
            if record is None:
                return None
            return Model.model_validate(record["m"])

    data = _run_sync(_async(model_name))
    if data is None:
        return None
    return data

def promote_checkpoint_to_model(
    ckp_uri: str,
    model_id: str,
    model_uri: str,
    model_name: str,
) -> str:
    """Promuove un Checkpoint a Model temporaneo, creando l'arco PROMOTED."""
    async def _async():
        driver = await client.get_driver()
        query = """
        MATCH (ckp:Checkpoint {uri: $ckp_uri})
        CREATE (m:Model {
            id: $model_id,
            model_name: $model_name,
            uri: $model_uri,
            promoted_from_ckp: true,
            created_at: datetime()
        })
        CREATE (ckp)-[:PROMOTED]->(m)
        RETURN m.id AS model_id
        """
        params = {
            "ckp_uri": ckp_uri,
            "model_id": model_id,
            "model_name": model_name,
            "model_uri": model_uri,
        }
        async with driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            if record is None:
                raise ValueError(f"Checkpoint with uri={ckp_uri} not found for promotion")
            return record["model_id"]

    return _run_sync(_async())