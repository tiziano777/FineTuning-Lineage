"""Repository for Experiment entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

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
        exp_id: str,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
    ) -> dict:
        """Create a new experiment.

        Args:
            exp_id: Unique experiment ID.
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
            exp_id: $exp_id,
            model_id: $model_id,
            status: $status,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at,
            usable: true
        })
        RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=exp_id,
            exp_id=exp_id,
            model_id=model_id,
            status=status,
            description=description,
            created_at=now,
            updated_at=now,
        )

        if not result:
            raise UIError("Failed to create experiment in Neo4j")

        logger.info(f"Experiment created: id={exp_id}, model_id={model_id}")
        return result

    async def create_experiment(
        self,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
    ) -> dict:
        """Create a new experiment (generates UUID automatically).

        Args:
            model_id: Associated Model ID.
            status: Experiment status (PENDING, RUNNING, COMPLETED, FAILED).
            description: Experiment description.

        Returns:
            Created experiment data.
        """
        import uuid
        exp_id = str(uuid.uuid4())
        return await self.create(
            exp_id=exp_id,
            model_id=model_id,
            status=status,
            description=description,
        )

    async def get_by_id(self, exp_id: str) -> Optional[dict]:
        """Get experiment by ID.

        Args:
            exp_id: Experiment ID.

        Returns:
            Experiment data or None if not found.
        """
        query = """
        MATCH (e:Experiment {id: $id})
        RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
               e.status as status, e.description as description,
               e.created_at as created_at, e.updated_at as updated_at
        """

        result = await self.db.run_single(query, id=exp_id)
        return result

    async def get_experiment(self, exp_id: str) -> Optional[dict]:
        """Alias for get_by_id for manager compatibility."""
        return await self.get_by_id(exp_id)

    async def list_all(self, status: Optional[str] = None) -> list[dict]:
        """List experiments optionally filtered by status.

        Args:
            status: Optional status filter.

        Returns:
            List of experiment dictionaries.
        """
        if status:
            query = """
            MATCH (e:Experiment {status: $status})
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.created_at as created_at, e.updated_at as updated_at
            LIMIT 100
            """
            results = await self.db.run_list(query, status=status)
        else:
            query = """
            MATCH (e:Experiment)
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.created_at as created_at, e.updated_at as updated_at
            LIMIT 100
            """
            results = await self.db.run_list(query)

        return results

    async def list_experiments(self, status: Optional[str] = None) -> list[dict]:
        """Alias for list_all for manager compatibility."""
        return await self.list_all(status=status)

    async def update(
        self,
        exp_id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
    ) -> dict:
        """Update experiment fields.

        Args:
            exp_id: Experiment ID.
            status: New status.
            description: New description.
            exit_status: Exit status.
            exit_msg: Exit message.

        Returns:
            Updated experiment data.
        """
        now = datetime.utcnow().isoformat()
        params = {"id": exp_id, "updated_at": now}

        # Build parameterized query based on which fields are provided
        if status is not None and description is not None and exit_status is not None and exit_msg is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.description = $description,
                e.exit_status = $exit_status, e.exit_msg = $exit_msg,
                e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params.update({"status": status, "description": description, "exit_status": exit_status, "exit_msg": exit_msg})
        elif status is not None and description is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.description = $description, e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params.update({"status": status, "description": description})
        elif status is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.status = $status, e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params["status"] = status
        elif description is not None:
            query = """
            MATCH (e:Experiment {id: $id})
            SET e.description = $description, e.updated_at = $updated_at
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """
            params["description"] = description
        else:
            query = """
            MATCH (e:Experiment {id: $id})
            RETURN e.id as id, e.exp_id as exp_id, e.model_id as model_id,
                   e.status as status, e.description as description,
                   e.updated_at as updated_at
            """

        result = await self.db.run_single(query, **params)

        if not result:
            raise UIError(f"Experiment {exp_id} not found")

        logger.info(f"Experiment updated: id={exp_id}")
        return result

    async def update_experiment(
        self,
        exp_id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
    ) -> dict:
        """Alias for update for manager compatibility."""
        return await self.update(
            exp_id=exp_id,
            status=status,
            description=description,
            exit_status=exit_status,
            exit_msg=exit_msg,
        )

    async def delete(self, exp_id: str) -> None:
        """Delete experiment with constraint checking.

        Args:
            exp_id: Experiment ID to delete.

        Raises:
            UIError: If experiment not found, has generated checkpoints,
                     or has derived/branched experiments.
        """
        existing = await self.get_by_id(exp_id)
        if not existing:
            raise UIError(f"Experiment '{exp_id}' not found")

        # Check if experiment can be deleted
        if not await self.is_deletable(exp_id):
            raise UIError(
                f"Cannot delete experiment '{exp_id}': it has produced checkpoints "
                "or has derived/branched experiments. "
                "Remove dependent experiments/checkpoints first."
            )

        try:
            query = "MATCH (e:Experiment {id: $id}) DETACH DELETE e"
            await self.db.run(query, id=exp_id)
            logger.warning(f"Experiment deleted: id={exp_id}")
        except Exception as e:
            logger.error(f"Experiment deletion failed: {exp_id}", exc_info=True)
            raise UIError(f"Failed to delete experiment: {str(e)}")

    async def delete_experiment(self, exp_id: str) -> None:
        """Alias for delete for manager compatibility."""
        await self.delete(exp_id)

    async def is_deletable(self, exp_id: str) -> bool:
        """Check if experiment can be deleted.

        Experiment cannot be deleted if:
        - It has outgoing PRODUCED relationships (generated checkpoints)
        - It has outgoing DERIVED_FROM relationships (has derived/branched experiments)
        - It has outgoing STARTED_FROM relationships (physical branching from checkpoints)
        - It has outgoing RETRY_OF relationships (experiment is base for retries)

        Args:
            exp_id: Experiment ID to check.

        Returns:
            True if experiment has no blocking outgoing relationships, False otherwise.
        """
        existing = await self.get_by_id(exp_id)
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
        result = await self.db.run_single(query, id=exp_id)
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

    async def count_dependencies(self, exp_id: str) -> int:
        """Count checkpoints for this experiment.

        Args:
            exp_id: Experiment ID.

        Returns:
            Number of dependent checkpoints.
        """
        query = """
        MATCH (e:Experiment {id: $id})-[r:HAS_CHECKPOINT]->(cp)
        RETURN count(r) as dep_count
        """

        result = await self.db.run_single(query, id=exp_id)
        return result["dep_count"] if result else 0

    async def check_experiment_dependencies(self, exp_id: str) -> int:
        """Alias for count_dependencies for manager compatibility."""
        return await self.count_dependencies(exp_id)

    async def list_rich(self, status_filter: str = None, search: str = None) -> list[dict]:
        """List experiments with USES_MODEL, USES_RECIPE, USES_TECHNIQUE relationships and checkpoint count."""
        query = """
        MATCH (e:Experiment)
        OPTIONAL MATCH (e)-[:USES_MODEL]->(m:Model)
        OPTIONAL MATCH (e)-[:USES_RECIPE]->(r:Recipe)
        OPTIONAL MATCH (e)-[:USES_TECHNIQUE]->(c:Component)
        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)
        WITH e, m, r, c, COUNT(ckp) as ckp_count
        RETURN e.exp_id as exp_id, e.status as status, e.description as description,
               e.usable as usable, e.config_hash as config_hash, e.created_at as created_at,
               e.notes as notes, m.model_name as model_name, r.name as recipe_name,
               c.technique_code as technique_code, c.framework_code as framework_code,
               ckp_count
        ORDER BY e.created_at DESC
        LIMIT 100
        """
        return await self.db.run_list(query)

    async def update_metadata(self, exp_id: str, description: str = None, notes: str = None) -> dict:
        """Update only description and notes fields (metadata edit)."""
        sets = []
        params = {"exp_id": exp_id, "updated_at": datetime.utcnow().isoformat()}
        if description is not None:
            sets.append("e.description = $description")
            params["description"] = description
        if notes is not None:
            sets.append("e.notes = $notes")
            params["notes"] = notes
        if not sets:
            raise UIError("No fields to update")
        query = f"MATCH (e:Experiment {{exp_id: $exp_id}}) SET {', '.join(sets)}, e.updated_at = $updated_at RETURN e.exp_id as exp_id"
        result = await self.db.run_single(query, **params)
        if not result:
            raise UIError("Experiment not found")
        return dict(result)

    async def get_agentic_metadata(self, exp_id: str) -> Optional[dict]:
        """Fetch only the agentic metadata fields for a given experiment.

        Args:
            exp_id: Experiment ID (exp_id property on the node).

        Returns:
            Dict with all agentic metadata fields, or None if experiment not found.
        """
        query = """
        MATCH (e:Experiment {exp_id: $exp_id})
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
        result = await self.db.run_single(query, exp_id=exp_id)
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
        exp_id: str,
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
            exp_id: Experiment ID (exp_id property, not internal id).
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
            Dict with exp_id confirming the write.

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
        field_map["exp_id"] = exp_id

        query = f"""
        MATCH (e:Experiment {{exp_id: $exp_id}})
        SET {', '.join(set_clauses)}
        RETURN e.exp_id AS exp_id
        """

        result = await self.db.run_single(query, **field_map)
        if not result:
            raise UIError(f"Experiment '{exp_id}' non trovato")

        return dict(result)
