"""Thin async wrapper functions for Neo4j operations used by the tracker.

All public functions are sync — they detect the event loop state and
use the appropriate strategy:
- No running loop: asyncio.run() (standard)
- Running loop (Jupyter, Streamlit, FastAPI): nest_asyncio + run_until_complete
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, replace
from typing import Any
import traceback
import nest_asyncio

from graph_lineage.data_classes.neo4j.nodes.base.enum.status_type import StatusType
from graph_lineage.data_classes.neo4j.nodes.code.generic.enum.strategy_type import StrategyType
from graph_lineage.data_classes.neo4j.nodes.code.training.checkpoint import Checkpoint
from graph_lineage.data_classes.neo4j.nodes.code.training.experiment import Experiment
from graph_lineage.data_classes.neo4j.nodes.code.training.model import Model
from graph_lineage.diff_util.description import generate_description
from graph_lineage.diff_util.snapshot import CodebaseSnapshot
from graph_lineage.neo4j_client.client import PersistentNeo4jClient
from graph_lineage.server.handlers.run_case_handler import RunTypeResult
from graph_lineage.server.schemas import PreRequest

logger = logging.getLogger(__name__)

# Edge type mapping per strategy — Experiment->Experiment edges only.
_STRATEGY_EXP_EDGE_MAP: dict[str, str] = {
    "BRANCH": "DERIVED_FROM",
    "RETRY": "RETRY_FROM",
    "MERGE": "MERGED_FROM",
}


@dataclass(kw_only=True)
class NodeCreationResult:
    """Risultato della creazione nodo Experiment (+ edge) nel grafo."""
    run_id: str
    description: str = ""


class TrainingRepository:
    """Handles Neo4j operations for the tracker with async/sync compatibility."""

    _nest_asyncio_applied = False
    _client = PersistentNeo4jClient(auto_init=True).get_instance()
    
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
    
    # ── Experiment operations ─────────────────────────────────────────────────
    
    @classmethod
    def find_experiment_by_id(cls, experiment_id: str) -> Experiment | None:
        """Find an experiment by its unique ID."""
        async def _async(experiment_id: str) -> Experiment | None:
            driver = await cls._client.get_driver()
            query = "MATCH (e:Experiment {id: $exp_id}) RETURN e LIMIT 1"
            async with driver.session() as session:
                result = await session.run(query, {"exp_id": experiment_id})
                record = await result.single()
                if record is None:
                    return None
                return Experiment.model_validate(record["e"])

        data = cls._run_sync(_async(experiment_id))
        if data is None:
            return None
        return Experiment.model_validate(data)
    
    @classmethod
    def find_parent_experiment_id(cls, experiment_id: str) -> str | None:
        """Find the parent experiment ID of a given experiment."""
        async def _async(experiment_id: str) -> str | None:
            driver = await cls._client.get_driver()
            query = """
            MATCH (child:Experiment {id: $exp_id})-[:DERIVED_FROM|RETRY_FROM]->(parent:Experiment)
            RETURN parent.id AS parent_id
            LIMIT 1
            """
            async with driver.session() as session:
                result = await session.run(query, {"exp_id": experiment_id})
                record = await result.single()
                if record is None:
                    return None
                return record["parent_id"]

        return cls._run_sync(_async(experiment_id))
    
    @classmethod
    def create_base_experiment_node_with_edges(
        cls,
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
            driver = await cls._client.get_driver()
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

        return cls._run_sync(_async(exp, recipe_name, component_name, model_name, resumed_from))
    
    @classmethod
    def create_non_base_experiment_with_chain_edge(
        cls,
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
            driver = await cls._client.get_driver()
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

        return cls._run_sync(_async(exp, parent_exp_id, strategy, edge_properties))
    
    @classmethod
    def update_experiment_status(
        cls,
        exp_id: str,
        status: str,
        exit_msg: str | None = None,
        metrics_uri: str | None = None,
    ) -> None:
        """Update experiment status in Neo4j."""
        async def _async(
            exp_id: str, status: str, exit_msg: str | None, metrics_uri: str | None
        ) -> None:
            driver = await cls._client.get_driver()
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

        cls._run_sync(_async(exp_id, status, exit_msg, metrics_uri))

    # ── Experiment creation orchestration ────────────────────────────────────

    @classmethod
    def create_experiment_nodes(cls, request: PreRequest, result: RunTypeResult) -> NodeCreationResult:
        """Crea nodo Experiment e relativi edge nel grafo.

        - NEW / RESUME -> base experiment, salva TUTTA la codebase, atomic con Recipe/Component/Model.
        - BRANCH / RETRY / MERGE -> non-base, salva DIFF patch, edge verso parent.
        - Per RESUME: promuove CKP a Model se necessario, cambia nome in derived__{parent}, traccia resumed_from.
        """
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
        exp_id = str(uuid.uuid4())
        is_base = result.strategy in ("NEW", "RESUME")

        exp_name = request.experiment_name
        resumed_from_name = None
        if result.strategy == "RESUME" and result.parent_run_id:
            parent_exp = cls.find_experiment_by_id(result.parent_run_id)
            if parent_exp:
                resumed_from_name = parent_exp.name
                exp_name = f"derived__{parent_exp.name}"
                logger.info(
                    "RESUME model switch: renaming experiment to '%s', resumed_from='%s'",
                    exp_name, resumed_from_name,
                )

        auto_description = generate_description(
            strategy=result.strategy,
            changed_files=result.changed_files,
            exp_id=result.parent_run_id,
            model_id=request.model_id,
        )
        description = request.description or auto_description

        extra = {**(result.extra or {}), "description": description}
        if resumed_from_name:
            extra["resumed_from"] = resumed_from_name
        result = replace(result, extra=extra)

        experiment = Experiment(
            id=exp_id,
            name=exp_name,
            description=description,
            uri=request.experiment_uri or "",
            run_type=request.user_domain,
            base=is_base,
            status=StatusType.RUNNING,
            strategy=StrategyType(result.strategy),
            model_id=request.model_id,
            codebase=json.dumps(snapshot.files) if is_base else json.dumps(result.diff_patch or {}),
            changed_files=result.changed_files or [],
            metrics_uri=None,
            model_uri=request.model_uri or None,
            resumed_from=resumed_from_name,
        )

        if is_base:
            if result.strategy == "RESUME" and request.model_id:
                db_model = cls.find_model_by_name(request.model_id)
                if db_model is None and request.model_uri:
                    try:
                        ckp_id = cls.retrieve_ckp_id_by_ckp_uri(request.model_uri)
                        logger.info(
                            "Model %s not found. Promoting CKP %s to temporary Model.",
                            request.model_id, request.model_uri,
                        )
                        cls.promote_checkpoint_to_model(
                            ckp_uri=request.model_uri,
                            model_id=request.model_id,
                            model_uri=request.model_uri,
                            model_name=request.model_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to promote CKP to Model for uri=%s: %s. "
                            "Atomic transaction will fail if Model does not exist.",
                            request.model_uri, e,
                        )

            logger.info(
                "Creating base experiment (atomic): exp_id=%s, name=%s, recipe=%s, component=%s, model=%s, resumed_from=%s",
                exp_id, exp_name, request.recipe_id, request.component_id, request.model_id, resumed_from_name,
            )
            cls.create_base_experiment_node_with_edges(
                exp=experiment,
                recipe_name=request.recipe_id,
                component_name=request.component_id,
                model_name=request.model_id,
                resumed_from=resumed_from_name,
            )
        else:
            edge_type = _STRATEGY_EXP_EDGE_MAP[result.strategy]
            edge_props: dict[str, Any] = {}
            if result.diff_patch:
                edge_props["diff_patch"] = str(result.diff_patch)

            logger.info(
                "Creating experiment with %s edge (atomic): exp_id=%s, parent_run_id=%s",
                edge_type, exp_id, result.parent_run_id,
            )
            cls.create_non_base_experiment_with_chain_edge(
                exp=experiment,
                parent_exp_id=result.parent_run_id,
                strategy=edge_type,
                edge_properties=edge_props or None,
            )

        return NodeCreationResult(run_id=exp_id, description=description)

    # ── Checkpoint operations ─────────────────────────────────────────────────
    
    @classmethod
    def retrieve_ckp_by_experiment_id(cls, exp_id: str) -> list[Checkpoint]:
        """Retrieve all Checkpoints produced by a given Experiment."""
        driver = cls._run_sync(cls._client.get_driver())
        query = """
        MATCH (e:Experiment {id: $exp_id})-[:PRODUCED]->(c:Checkpoint)
        RETURN c
        """
        async def _async() -> list[Checkpoint]:
            async with driver.session() as session:
                result = await session.run(query, {"exp_id": exp_id})
                records = await result.data()
                return [Checkpoint.model_validate(record["c"]) for record in records]
        return cls._run_sync(_async())
    
    @classmethod
    def retrieve_ckp_id_by_ckp_uri(cls, ckp_uri: str) -> str:
        """Retrieve the Checkpoint ID that matches a given checkpoint URI."""
        driver = cls._run_sync(cls._client.get_driver())
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
        return cls._run_sync(_async())
    
    @classmethod
    def find_experiment_from_chain(cls, base_exp_id: str, ckp_uri: str) -> Experiment:
        """Find the experiment that produced a checkpoint with the given URI."""
        driver = cls._run_sync(cls._client.get_driver())
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

        return cls._run_sync(_async())
    
    # ── Model operations ─────────────────────────────────────────────────────
    
    @classmethod
    def find_model_by_name(cls, model_name: str) -> Model | None:
        """Find a model node by its name."""
        async def _async(model_name: str) -> Model | None:
            driver = await cls._client.get_driver()
            query = "MATCH (m:Model {model_name: $model_name}) RETURN m LIMIT 1"
            async with driver.session() as session:
                result = await session.run(query, {"model_name": model_name})
                record = await result.single()
                if record is None:
                    return None
                return Model.model_validate(record["m"])

        data = cls._run_sync(_async(model_name))
        if data is None:
            return None
        return data
    
    @classmethod
    def promote_checkpoint_to_model(
        cls,
        ckp_uri: str,
        model_id: str,
        model_uri: str,
        model_name: str,
    ) -> str:
        """Promote a Checkpoint to a temporary Model, creating the PROMOTED edge."""
        async def _async():
            driver = await cls._client.get_driver()
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

        return cls._run_sync(_async())
