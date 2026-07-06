"""Repository for Experiment entity - Neo4j data access layer."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional, Any

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)
"""
PATCH per graph_lineage/streamlit_ui/db/repository/experiment_repository.py
Aggiungere i seguenti metodi alla classe ExperimentRepository esistente.
"""

import json
from datetime import datetime
from typing import Any, Optional

# ── Costanti per i campi agentici ─────────────────────────────────────────────

SCOPE_OPTIONS = [
    "baseline",
    "ablation",
    "hyperparameter_search",
    "architecture_change",
    "data_experiment",
    "regression_check",
]

CONCLUSION_TYPE_OPTIONS = [
    "confirmed",
    "refuted",
    "inconclusive",
    "unexpected",
    "error",
]

RETRY_POLICY_OPTIONS = [
    "none",
    "on_failure",
    "always",
    "if_promising",
]

VALIDATION_SCOPE_OPTIONS = [
    "train_only",
    "held_out",
    "full_benchmark",
    "human_eval",
]

class ExperimentRepository:
    """Data access layer for Experiment entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client

    async def create(
        self,
        id: str,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
    ) -> Experiment:
        """Create a new experiment.

        Args:
            id: Unique experiment ID.
            model_id: Associated Model ID.
            status: Experiment status.
            description: Experiment description.

        Returns:
            Created experiment data.
        """
        now = datetime.utcnow().isoformat()

        query = """
        CREATE (e:Experiment {
            id: $id,
            id: $id,
            model_id: $model_id,
            status: $status,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at,
            usable: true
        })
        RETURN e.id as id, e.id as id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=id,
            model_id=model_id,
            status=status,
            description=description,
            created_at=now,
            updated_at=now,
        )

        if not result:
            raise UIError("Failed to create experiment in Neo4j")

        logger.info(f"Experiment created: id={id}, model_id={model_id}")
        return Experiment(**result)

    async def create_experiment(
        self,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
    ) -> Experiment:
        """Create a new experiment (generates UUID automatically).

        Args:
            model_id: Associated Model ID.
            status: Experiment status (PENDING, RUNNING, COMPLETED, FAILED).
            description: Experiment description.

        Returns:
            Created experiment data.
        """
        import uuid
        id = str(uuid.uuid4())
        return await self.create(
            id=id,
            model_id=model_id,
            status=status,
            description=description,
        )

    async def get_by_id(self, id: str) -> Optional[Experiment]:
        """Get experiment by ID.

        Args:
            id: Experiment ID.

        Returns:
            Experiment object or None if not found.
        """
        query = """
        MATCH (e:Experiment {id: $id})
        RETURN e.id as id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        """

        result = await self.db.run_single(query, id=id)
        return Experiment(**result) if result else None

    async def get_experiment(self, id: str) -> Optional[Experiment]:
        """Alias for get_by_id for manager compatibility."""
        return await self.get_by_id(id)

    async def list_all(self, status: Optional[str] = None) -> list[Experiment]:
        """List all experiments optionally filtered by status.

        Args:
            status: Optional status filter.

        Returns:
            List of Experiment objects.
        """
        return await self.list_with_limit(
            limit=100,
            offset=0,
            status=status
        )

    async def list_with_limit(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> list[Experiment]:
        """List experiments with pagination support.
        
        Args:
            limit: Maximum number of experiments to return.
            offset: Number of experiments to skip (for pagination).
            status: Optional status filter.
            
        Returns:
            List of Experiment objects.
        """
        where_clause = ""
        params = {"limit": limit, "offset": offset}
        if status:
            where_clause = "WHERE e.status = $status"
            params["status"] = status
        
        query = f"""
        MATCH (e:Experiment)
        {where_clause}
        RETURN e.id as id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        ORDER BY e.created_at DESC
        SKIP $offset LIMIT $limit
        """
        results = await self.db.run_list(query, **params)
        return [Experiment(**row) for row in results]

    async def list_experiments(self, status: Optional[str] = None) -> list[Experiment]:
        """Alias for list_all for manager compatibility."""
        return await self.list_all(status=status)

    async def update(
        self,
        id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
    ) -> Experiment:
        """Update experiment fields.

        Args:
            id: Experiment ID.
            status: New status.
            description: New description.
            exit_status: Exit status.
            exit_msg: Exit message.

        Returns:
            Updated experiment data.
        """
        now = datetime.utcnow().isoformat()
        params = {"id": id, "updated_at": now}

        # Build parameterized query based on which fields are provided
        if status is not None and description is not None and exit_status is not None and exit_msg is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.description = $description,
                e.exit_status = $exit_status, e.exit_msg = $exit_msg,
                e.updated_at = $updated_at
            RETURN e.id as id, e.id as id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params.update({"status": status, "description": description, "exit_status": exit_status, "exit_msg": exit_msg})
        elif status is not None and description is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.description = $description, e.updated_at = $updated_at
            RETURN e.id as id, e.id as id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params.update({"status": status, "description": description})
        elif status is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.updated_at = $updated_at
            RETURN e.id as id, e.id as id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params["status"] = status
        elif description is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.description = $description, e.updated_at = $updated_at
            RETURN e.id as id, e.id as id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params["description"] = description
        else:
            query = """
            MATCH (e:Experiment {id: $id})
            RETURN e.id as id, e.id as id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """

        result = await self.db.run_single(query, **params)

        if not result:
            raise UIError(f"Experiment {id} not found")

        logger.info(f"Experiment updated: id={id}")
        return Experiment(**result)

    async def update_experiment(
        self,
        id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
    ) -> Experiment:
        """Alias for update for manager compatibility."""
        return await self.update(
            id=id,
            status=status,
            description=description,
            exit_status=exit_status,
            exit_msg=exit_msg,
        )

    async def delete(self, id: str) -> None:
        """Delete experiment with constraint checking.

        Args:
            id: Experiment ID to delete.

        Raises:
            UIError: If experiment not found, has generated checkpoints,
                     or has derived/branched experiments.
        """
        existing = await self.get_by_id(id)
        if not existing:
            raise UIError(f"Experiment '{id}' not found")

        # Check if experiment can be deleted
        if not await self.is_deletable(id):
            raise UIError(
                f"Cannot delete experiment '{id}': it has produced checkpoints "
                "or has derived/branched experiments. "
                "Remove dependent experiments/checkpoints first."
            )

        try:
            query = "MATCH (e:Experiment {id: $id}) DETACH DELETE e"
            await self.db.run(query, id=id)
            logger.warning(f"Experiment deleted: id={id}")
        except Exception as e:
            logger.error(f"Experiment deletion failed: {id}", exc_info=True)
            raise UIError(f"Failed to delete experiment: {str(e)}")

    async def delete_experiment(self, id: str) -> None:
        """Alias for delete for manager compatibility."""
        await self.delete(id)

    async def is_deletable(self, id: str) -> bool:
        """Check if experiment can be deleted.

        Experiment cannot be deleted if:
        - It has outgoing PRODUCED relationships (generated checkpoints)
        - It has outgoing DERIVED_FROM relationships (has derived/branched experiments)
        - It has outgoing STARTED_FROM relationships (physical branching from checkpoints)
        - It has outgoing RETRY_OF relationships (experiment is base for retries)

        Args:
            id: Experiment ID to check.

        Returns:
            True if experiment has no blocking outgoing relationships, False otherwise.
        """
        existing = await self.get_by_id(id)
        if not existing:
            return True

        # Query for blocking outgoing relationships
        query = """
        MATCH (e:Experiment {id: $id})
        OPTIONAL MATCH (e)-[:PRODUCED]->(cp:Checkpoint)
        OPTIONAL MATCH (e)-[:DERIVED_FROM]->(e2:Experiment)
        OPTIONAL MATCH (e)-[:STARTED_FROM]->(cp2:Checkpoint)
        OPTIONAL MATCH (e)-[:RETRY_OF]->(e3:Experiment)
        RETURN COUNT(DISTINCT cp) as produced_count,
               COUNT(DISTINCT e2) as derived_count,
               COUNT(DISTINCT cp2) as started_from_count,
               COUNT(DISTINCT e3) as retry_count
        """
        result = await self.db.run_single(query, id=id)
        if result:
            produced_count = result.get("produced_count", 0)
            derived_count = result.get("derived_count", 0)
            started_from_count = result.get("started_from_count", 0)
            retry_count = result.get("retry_count", 0)
            return (
                produced_count == 0
                and derived_count == 0
                and started_from_count == 0
                and retry_count == 0
            )
        return True

    async def count_dependencies(self, id: str) -> int:
        """Count checkpoints for this experiment.

        Args:
            id: Experiment ID.

        Returns:
            Number of dependent checkpoints.
        """
        query = """
        MATCH (e:Experiment {id: $id})-[r:HAS_CHECKPOINT]->(cp)
        RETURN count(r) as dep_count
        """

        result = await self.db.run_single(query, id=id)
        return result["dep_count"] if result else 0

    async def check_experiment_dependencies(self, id: str) -> int:
        """Alias for count_dependencies for manager compatibility."""
        return await self.count_dependencies(id)

    async def list_rich(self, status_filter: str = None, search: str = None) -> list[Experiment]:
        """List experiments with USES_MODEL, USES_RECIPE, USES_TECHNIQUE relationships and checkpoint count.
        
        Returns:
            List of Experiment objects with UI metadata nested in custom_fields.
        """
        query = """
        MATCH (e:Experiment)
        OPTIONAL MATCH (e)-[:USES_MODEL]->(m:Model)
        OPTIONAL MATCH (e)-[:USES_RECIPE]->(r:Recipe)
        OPTIONAL MATCH (e)-[:USES_TECHNIQUE]->(c:Component)
        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)
        WITH e, m, r, c, COUNT(ckp) as ckp_count
        RETURN 
            e.id, e.status, e.description, e.uri, e.base, e.name, e.chain_id,
            e.exit_status, e.exit_msg, e.strategy, e.experiment_type,
            e.model_id, e.model_uri, e.recipe_id, e.component_id,
            e.codebase, e.changed_files, e.usable, e.manual_save, e.metrics_uri,
            e.created_at, e.updated_at,
            m.model_name as model_name, r.name as recipe_name,
            c.technique_code as technique_code, c.framework_code as framework_code,
            ckp_count, e.config_hash,
            e.scope, e.hypothesis, e.motivation, e.conclusion, e.conclusion_type,
            e.evidences, e.open_questions, e.is_base, e.exploration_priority,
            e.dead_end, e.tags, e.confidence, e.retry_policy, e.validation_scope,
            e.compute_cost, e.duration_seconds, e.estimated_gain,
            e.notes
        ORDER BY e.created_at DESC
        LIMIT 100
        """
        results = await self.db.run_list(query)
        experiments = []
        for row in results:
            exp = Experiment(
                id=row.get("id"),
                status=row.get("status"),
                description=row.get("description"),
                uri=row.get("uri", ""),
                base=row.get("base", True),
                name=row.get("name", ""),
                chain_id=row.get("chain_id", 0),
                exit_status=row.get("exit_status"),
                exit_msg=row.get("exit_msg"),
                strategy=row.get("strategy", ""),
                experiment_type=row.get("experiment_type", "training"),
                model_id=row.get("model_id"),
                model_uri=row.get("model_uri"),
                recipe_id=row.get("recipe_id"),
                component_id=row.get("component_id"),
                codebase=row.get("codebase", ""),
                changed_files=row.get("changed_files") or [],
                usable=row.get("usable", True),
                manual_save=row.get("manual_save", False),
                metrics_uri=row.get("metrics_uri"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
            # Store UI-specific metadata in custom_fields
            if exp.__dict__ is not None:  # Allow dynamic assignment
                exp.model_name = row.get("model_name")
                exp.recipe_name = row.get("recipe_name")
                exp.technique_code = row.get("technique_code")
                exp.framework_code = row.get("framework_code")
                exp.ckp_count = row.get("ckp_count", 0)
                exp.config_hash = row.get("config_hash")
                exp.notes = row.get("notes")
                # Agentic metadata
                exp.scope = row.get("scope")
                exp.hypothesis = row.get("hypothesis")
                exp.motivation = row.get("motivation")
                exp.conclusion = row.get("conclusion")
                exp.conclusion_type = row.get("conclusion_type")
                exp.evidences = row.get("evidences")
                exp.open_questions = row.get("open_questions")
                exp.is_base_exp = row.get("is_base")  # Rename to avoid collision with base
                exp.exploration_priority = row.get("exploration_priority")
                exp.dead_end = row.get("dead_end")
                exp.tags = row.get("tags")
                exp.confidence = row.get("confidence")
                exp.retry_policy = row.get("retry_policy")
                exp.validation_scope = row.get("validation_scope")
                exp.compute_cost = row.get("compute_cost")
                exp.duration_seconds = row.get("duration_seconds")
                exp.estimated_gain = row.get("estimated_gain")
            
            experiments.append(exp)
        
        return experiments

    async def update_metadata(self, id: str, description: str = None, notes: str = None) -> Experiment:
        """Update only description and notes fields (metadata edit).
        
        Returns:
            Updated Experiment object.
        """
        sets = []
        params = {"id": id, "updated_at": datetime.utcnow().isoformat()}
        if description is not None:
            sets.append("e.description = $description")
            params["description"] = description
        if notes is not None:
            sets.append("e.notes = $notes")
            params["notes"] = notes
        if not sets:
            raise UIError("No fields to update")
        
        query = f"""
        MATCH (e:Experiment {{id: $id}})
        SET {', '.join(sets)}, e.updated_at = $updated_at
        RETURN 
            e.id, e.status, e.description, e.uri, e.base, e.name, e.chain_id,
            e.exit_status, e.exit_msg, e.strategy, e.experiment_type,
            e.model_id, e.model_uri, e.recipe_id, e.component_id,
            e.codebase, e.changed_files, e.usable, e.manual_save, e.metrics_uri,
            e.created_at, e.updated_at, e.notes
        """
        result = await self.db.run_single(query, **params)
        if not result:
            raise UIError("Experiment not found")
        
        return Experiment(**{k: v for k, v in result.items() if k in Experiment.model_fields})

    async def get_agentic_metadata(self, id: str) -> Optional[dict]:
        """Fetch only the agentic metadata fields for a given experiment.

        Args:
            id: Experiment ID (id property on the node).

        Returns:
            Dict with all agentic metadata fields, or None if experiment not found.
        """
        query = """
        MATCH (e:Experiment {id: $id})
        RETURN
            e.scope                AS scope,
            e.hypothesis           AS hypothesis,
            e.motivation           AS motivation,
            e.conclusion           AS conclusion,
            e.conclusion_type      AS conclusion_type,
            e.evidences            AS evidences,
            e.open_questions       AS open_questions,
            e.is_base              AS is_base,
            e.exploration_priority AS exploration_priority,
            e.dead_end             AS dead_end,
            e.tags                 AS tags,
            e.confidence           AS confidence,
            e.retry_policy         AS retry_policy,
            e.validation_scope     AS validation_scope,
            e.compute_cost         AS compute_cost,
            e.duration_seconds     AS duration_seconds,
            e.estimated_gain       AS estimated_gain
        """
        result = await self.db.run_single(query, id=id)
        if result is None:
            return None

        # Deserializza i campi JSON serializzati come stringa
        for json_field in ("evidences", "open_questions", "tags"):
            raw = result.get(json_field)
            if isinstance(raw, str):
                try:
                    result[json_field] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    result[json_field] = []
            elif raw is None:
                result[json_field] = [] if json_field in ("open_questions", "tags") else None

        return dict(result)

    async def update_agentic_metadata(
        self,
        id: str,
        *,
        # Gruppo 1 — identità
        scope: Optional[str] = None,
        hypothesis: Optional[str] = None,
        motivation: Optional[str] = None,
        # Gruppo 2 — conoscenza post-run
        conclusion: Optional[str] = None,
        conclusion_type: Optional[str] = None,
        evidences: Optional[list[dict]] = None,
        open_questions: Optional[list[str]] = None,
        # Gruppo 3 — navigabilità
        is_base: Optional[bool] = None,
        exploration_priority: Optional[float] = None,
        dead_end: Optional[bool] = None,
        tags: Optional[list[str]] = None,
        # Gruppo 4 — affidabilità
        confidence: Optional[float] = None,
        retry_policy: Optional[str] = None,
        validation_scope: Optional[str] = None,
        # Gruppo 5 — costi
        compute_cost: Optional[float] = None,
        duration_seconds: Optional[int] = None,
        estimated_gain: Optional[float] = None,
    ) -> dict:
        """Update agentic/epistemic metadata fields on an :Experiment node.

        Only fields explicitly passed (non-None) are written. Fields left as None
        are NOT touched, preserving whatever was already stored.

        JSON array fields (evidences, open_questions, tags) are serialised to
        strings before writing, because Neo4j stores them as node properties
        and the driver handles list<string> natively but list<dict> is safer
        as JSON strings.

        Args:
            id: Experiment ID (id property, not internal id).
            scope: Macro-category enum.
            hypothesis: Claim to be verified, written pre-run.
            motivation: Why this experiment was created.
            conclusion: Post-run narrative summary.
            conclusion_type: Epistemic outcome enum.
            evidences: Structured list of metric observations.
            open_questions: Open research questions generated by this run.
            is_base: Whether this is a baseline/reference experiment.
            exploration_priority: Agent's confidence in this direction [0-1].
            dead_end: Whether this direction should not be explored further.
            tags: Free-form labels for semantic clustering.
            confidence: Reliability of result [0-1].
            retry_policy: Retry behaviour enum.
            validation_scope: Granularity of evaluation enum.
            compute_cost: Estimated GPU-hours or token equivalent.
            duration_seconds: Actual wall-clock duration of the run.
            estimated_gain: Predicted delta on primary metric (pre-run).

        Returns:
            Dict with id confirming the write.

        Raises:
            UIError: If no fields provided or experiment not found.
        """
        from graph_lineage.streamlit_ui.utils.errors import UIError  # local import to avoid circular

        # Mappa campo → valore, serializzando dove necessario
        field_map: dict[str, Any] = {}

        # Scalari semplici
        for name, val in [
            ("scope", scope),
            ("hypothesis", hypothesis),
            ("motivation", motivation),
            ("conclusion", conclusion),
            ("conclusion_type", conclusion_type),
            ("is_base", is_base),
            ("exploration_priority", exploration_priority),
            ("dead_end", dead_end),
            ("confidence", confidence),
            ("retry_policy", retry_policy),
            ("validation_scope", validation_scope),
            ("compute_cost", compute_cost),
            ("duration_seconds", duration_seconds),
            ("estimated_gain", estimated_gain),
        ]:
            if val is not None:
                field_map[name] = val

        # Array/JSON — serializzati come stringa per uniformità
        if evidences is not None:
            field_map["evidences"] = json.dumps(evidences, ensure_ascii=False)
        if open_questions is not None:
            field_map["open_questions"] = json.dumps(open_questions, ensure_ascii=False)
        if tags is not None:
            # tags è una lista di stringhe: il driver Neo4j la gestisce nativamente
            field_map["tags"] = tags

        if not field_map:
            raise UIError("Nessun campo da aggiornare fornito")

        # Costruisce SET dinamico (parametrizzato, nessun rischio di injection)
        set_clauses = [f"e.{k} = ${k}" for k in field_map]
        set_clauses.append("e.updated_at = $updated_at")
        field_map["updated_at"] = datetime.utcnow().isoformat()
        field_map["id"] = id

        query = f"""
        MATCH (e:Experiment {{id: $id}})
        SET {', '.join(set_clauses)}
        RETURN e.id AS id
        """

        result = await self.db.run_single(query, **field_map)
        if not result:
            raise UIError(f"Experiment '{id}' non trovato")

        return dict(result)
