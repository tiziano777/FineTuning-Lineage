"""Repository for Experiment entity — Neo4j data access layer."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient
from graph_lineage.streamlit_ui.utils.errors import UIError

logger = logging.getLogger(__name__)

# ── Constants for agentic enums (used for UI hints, not DB constraints) ──

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

# ── Fields known to be stored as JSON strings in Neo4j ──
# These are deserialized from JSON when reading from Neo4j.
# All other string fields are left as-is to avoid accidental
# deserialization of legitimate string values.

JSON_SERIALIZED_FIELDS: Set[str] = {
    "codebase",
    "evidences",
    "open_questions",
    "tags",
    "lessons_learned",
    "changed_files",
    # Add any other field that is stored as JSON in Neo4j
}

def _serialize_for_neo4j(value: Any) -> Any:
    """Serialize Python values for Neo4j storage.

    - list/dict -> JSON string (Neo4j stores strings reliably; lists of primitives
      work natively but dicts inside lists need JSON)
    - datetime with to_native -> convert
    - Everything else -> as-is
    """
    if value is None:
        return None
    if hasattr(value, "to_native") and callable(value.to_native):
        return value.to_native()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value

def _deserialize_from_neo4j(field_name: str, value: Any) -> Any:
    """Deserialize Neo4j values back to Python.

    Only fields in JSON_SERIALIZED_FIELDS are parsed as JSON.
    All other values are returned as-is, preventing accidental
    deserialization of legitimate string content.
    """
    if value is None:
        return None
    if field_name in JSON_SERIALIZED_FIELDS and isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value

def _flatten_experiment(exp: Experiment) -> Dict[str, Any]:
    """Convert Experiment to flat dict for Cypher parameters.

    All declared fields + extra fields are flattened. Complex types are serialized.
    """
    # model_dump with extra='allow' already includes extra fields as top-level keys
    data: Dict[str, Any] = exp.model_dump(mode="json", exclude_none=False)

    # Serialize complex types for Neo4j
    return {k: _serialize_for_neo4j(v) for k, v in data.items()}

def _row_to_experiment(row: Dict[str, Any]) -> Experiment:
    """Convert a Neo4j result row to an Experiment object.

    Deserializes JSON strings only for known fields and passes everything
    through to Pydantic. Extra fields are preserved via extra='allow'.
    """
    deserialized = {
        k: _deserialize_from_neo4j(k, v)
        for k, v in row.items()
    }
    return Experiment(**deserialized)

class ExperimentRepository:
    """Data access layer for Experiment entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        self.db = db_client

    # ── CRUD: Create ──

    async def create(self, experiment: Experiment) -> Experiment:
        """Create a new experiment node. All fields (including extra) are persisted."""

        data = _flatten_experiment(experiment)

        # Build dynamic Cypher
        fields = list(data.keys())
        props = ", ".join(f"{k}: ${k}" for k in fields)

        query = f"""
        CREATE (e:Experiment {{{props}}})
        RETURN e {{.*}} AS node
        """

        result = await self.db.run_single(query, **data)
        if not result:
            raise UIError("Failed to create experiment in Neo4j")

        logger.info(f"Experiment created: id={experiment.id}")
        return _row_to_experiment(result["node"])

    async def create_experiment(
        self,
        model_id: str,
        status: str = "PENDING",
        description: str = "",
        **kwargs: Any,
    ) -> Experiment:
        """Convenience: create with minimal args, rest via kwargs (extra fields)."""
        exp = Experiment(
            model_id=model_id,
            status=status,  # type: ignore[arg-type]
            description=description,
            **kwargs,
        )
        return await self.create(exp)

    # ── CRUD: Read ──

    async def get_by_id(self, id: str) -> Optional[Experiment]:
        """Get experiment by ID. Returns full object with all extra fields."""
        query = """
        MATCH (e:Experiment {id: $id})
        RETURN e {.*} AS node
        """
        result = await self.db.run_single(query, id=id)
        return _row_to_experiment(result["node"]) if result else None

    async def get_experiment(self, id: str) -> Optional[Experiment]:
        """Alias for manager compatibility."""
        return await self.get_by_id(id)

    async def list_all(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Experiment]:
        """List experiments with optional status filter and pagination."""
        where_clause = ""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            where_clause = "WHERE e.status = $status"
            params["status"] = status

        query = f"""
        MATCH (e:Experiment)
        {where_clause}
        RETURN e {{.*}} AS node
        ORDER BY e.created_at DESC
        SKIP $offset LIMIT $limit
        """
        results = await self.db.run_list(query, **params)
        return [_row_to_experiment(r["node"]) for r in results]

    async def list_with_limit(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[Experiment]:
        """Alias with explicit pagination args."""
        return await self.list_all(status=status, limit=limit, offset=offset)

    async def list_experiments(self, status: Optional[str] = None) -> List[Experiment]:
        """Alias for manager compatibility."""
        return await self.list_all(status=status)

    async def list_rich(
        self,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Experiment]:
        """List experiments with related nodes and ALL properties.

        Returns Experiment objects where extra fields (including agentic metadata)
        are preserved via Pydantic extra='allow'.

        Note: This method resolves only DIRECT relationships (USES_MODEL, etc.).
        For lineage-resolved resources, use list_rich_with_lineage().
        """
        where_clauses: List[str] = []
        params: Dict[str, Any] = {}

        if status_filter:
            where_clauses.append("e.status = $status_filter")
            params["status_filter"] = status_filter
        if search:
            where_clauses.append(
                "(e.id CONTAINS $search OR e.description CONTAINS $search OR e.name CONTAINS $search)"
            )
            params["search"] = search

        where_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
        MATCH (e:Experiment)
        OPTIONAL MATCH (e)-[:USES_MODEL]->(m:Model)
        OPTIONAL MATCH (e)-[:USES_RECIPE]->(r:Recipe)
        OPTIONAL MATCH (e)-[:USES_COMPONENT]->(c:Component)
        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)
        {where_str}
        WITH e, m, r, c, COUNT(ckp) AS ckp_count
        RETURN e {{.*,
            model_name: m.model_name,
            recipe_name: r.name,
            technique_code: c.technique_code,
            framework_code: c.framework_code,
            ckp_count: ckp_count
        }} AS node
        ORDER BY node.created_at DESC  // <--- MODIFICATO QUI (era e.created_at)
        LIMIT 100
        """
        results = await self.db.run_list(query, **params)
        return [_row_to_experiment(r["node"]) for r in results]

    # ── CRUD: Update ──

    async def update(
        self,
        id: str,
        experiment: Optional[Experiment] = None,
        **fields: Any,
    ) -> Experiment:
        """Update experiment by ID.

        Pass either a full Experiment object OR keyword args for partial update.
        Extra fields in kwargs are automatically persisted.

        To explicitly set a field to None, pass the sentinel _UNSET.
        To set a field to a falsy value (0, "", []), pass it normally.
        """
        if experiment is not None and fields:
            raise UIError("Pass either experiment= OR kwargs, not both.")

        if experiment is not None:
            data = _flatten_experiment(experiment)
            data.pop("id", None)  # Don't overwrite id
        else:
            # Use a sentinel to distinguish "not provided" from "set to None"
            _UNSET = object()
            data = {}
            for k, v in fields.items():
                if v is _UNSET:
                    data[k] = None  # Explicitly set to None
                elif v is not None:
                    data[k] = _serialize_for_neo4j(v)
                elif k in ("usable", "base", "dead_end", "is_base", "manual_save"):
                    # Boolean fields: None means "not provided", False is valid
                    pass  # Skip None for boolean fields unless explicitly set
                else:
                    # For other fields, None means "remove/unset" — include it
                    data[k] = None

        if not data:
            raise UIError("No fields provided for update")

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        data["id"] = id  # For the MATCH clause

        set_clauses = [f"e.{k} = ${k}" for k in data if k != "id"]

        query = f"""
        MATCH (e:Experiment {{id: $id}})
        SET {', '.join(set_clauses)}
        RETURN e {{.*}} AS node
        """

        result = await self.db.run_single(query, **data)
        if not result:
            raise UIError(f"Experiment '{id}' not found")

        logger.info(f"Experiment updated: id={id}")
        return _row_to_experiment(result["node"])

    async def update_experiment(
        self,
        id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        exit_status: Optional[str] = None,
        exit_msg: Optional[str] = None,
        **kwargs: Any,
    ) -> Experiment:
        """Alias for manager compatibility with explicit args + extra kwargs."""
        return await self.update(
            id=id,
            status=status,
            description=description,
            exit_status=exit_status,
            exit_msg=exit_msg,
            **kwargs,
        )

    async def update_metadata(
        self,
        id: str,
        description: Optional[str] = None,
        notes: Optional[str] = None,
        **extra: Any,
    ) -> Experiment:
        """Update metadata fields (description, notes, and any extra fields)."""
        fields = {}
        if description is not None:
            fields["description"] = description
        if notes is not None:
            fields["notes"] = notes
        fields.update(extra)
        return await self.update(id=id, **fields)

    # ── Agentic metadata ──

    async def get_agentic_metadata(self, id: str) -> Dict[str, Any]:
        """Fetch all agentic metadata fields for a given experiment.

        Returns a flat dict with all non-core properties. Extra fields are
        included automatically because we don't hardcode the RETURN.
        """
        query = """
        MATCH (e:Experiment {id: $id})
        RETURN e {.*} AS node
        """
        result = await self.db.run_single(query, id=id)
        if not result:
            return {}

        node = result["node"]
        # Core fields to exclude — everything else is considered agentic/extra
        core_fields = {
            "id",
            "created_at",
            "updated_at",
            "description",
            "uri",
            "base",
            "name",
            "chain_id",
            "status",
            "exit_status",
            "exit_msg",
            "strategy",
            "experiment_type",
            "model_id",
            "model_uri",
            "recipe_id",
            "component_id",
            "codebase",
            "changed_files",
            "usable",
            "manual_save",
            "metrics_uri",
            # UI-computed fields from list_rich / list_rich_with_lineage
            "model_name",
            "recipe_name",
            "technique_code",
            "framework_code",
            "ckp_count",
        }
        return {
            k: _deserialize_from_neo4j(k, v)
            for k, v in node.items()
            if k not in core_fields
        }

    async def update_agentic_metadata(
        self,
        id: str,
        agentic_metadata: Optional[Dict[str, Any]] = None,
        **flat_fields: Any,
    ) -> Experiment:
        """Update agentic metadata as a nested dict OR flat fields.

        If agentic_metadata dict is provided, its keys are flattened and stored
        as individual node properties (enabling Neo4j indexing/querying).
        If flat fields are provided, they are stored directly.
        """
        if agentic_metadata is not None and flat_fields:
            raise UIError("Pass either agentic_metadata= OR flat kwargs, not both.")

        if agentic_metadata is not None:
            # Flatten nested dict into individual properties
            payload = {
                k: _serialize_for_neo4j(v)
                for k, v in agentic_metadata.items()
            }
        else:
            payload = flat_fields

        return await self.update(id=id, **payload)

    # ── CRUD: Delete ──

    async def delete(self, id: str) -> None:
        """Delete experiment with constraint checking."""
        existing = await self.get_by_id(id)
        if not existing:
            raise UIError(f"Experiment '{id}' not found")

        if not await self.is_deletable(id):
            raise UIError(
                f"Cannot delete experiment '{id}': it has produced checkpoints "
                "or has derived/branched experiments. Remove dependents first."
            )

        query = "MATCH (e:Experiment {id: $id}) DETACH DELETE e"
        await self.db.run(query, id=id)
        logger.warning(f"Experiment deleted: id={id}")

    async def delete_experiment(self, id: str) -> None:
        """Alias for manager compatibility."""
        await self.delete(id)

    async def is_deletable(self, id: str) -> bool:
        """Check if experiment has no blocking outgoing relationships."""
        query = """
        MATCH (e:Experiment {id: $id})
        OPTIONAL MATCH (e)-[:PRODUCED]->(cp:Checkpoint)
        OPTIONAL MATCH (e)-[:DERIVED_FROM]->(e2:Experiment)
        OPTIONAL MATCH (e)-[:STARTED_FROM]->(cp2:Checkpoint)
        OPTIONAL MATCH (e)-[:RETRY_OF]->(e3:Experiment)
        RETURN COUNT(DISTINCT cp) AS produced_count,
               COUNT(DISTINCT e2) AS derived_count,
               COUNT(DISTINCT cp2) AS started_from_count,
               COUNT(DISTINCT e3) AS retry_count
        """
        result = await self.db.run_single(query, id=id)
        if result:
            return all(
                result.get(k, 0) == 0
                for k in ("produced_count", "derived_count", "started_from_count", "retry_count")
            )
        return True

    async def count_dependencies(self, id: str) -> int:
        """Count checkpoints linked to this experiment."""
        query = """
        MATCH (e:Experiment {id: $id})-[:HAS_CHECKPOINT]->(cp)
        RETURN COUNT(cp) AS dep_count
        """
        result = await self.db.run_single(query, id=id)
        return result["dep_count"] if result else 0

    async def check_experiment_dependencies(self, id: str) -> int:
        """Alias for manager compatibility."""
        return await self.count_dependencies(id)

    # ── Graph lineage resolution ──

    async def list_rich_with_lineage(
        self,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Experiment]:
        """List experiments with resolved lineage resources (Model, Recipe, Component).

        For each experiment, walks the DERIVED_FROM|RETRY_OF|RESUMED_FROM chain
        backwards to find the nearest ancestor with USES_* relationships.
        """
        where_clauses: List[str] = []
        params: Dict[str, Any] = {}

        if status_filter:
            where_clauses.append("e.status = $status_filter")
            params["status_filter"] = status_filter
        if search:
            where_clauses.append(
                "(e.id CONTAINS $search OR e.name CONTAINS $search OR e.description CONTAINS $search)"
            )
            params["search"] = search

        where_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
        MATCH (e:Experiment)
        {where_str}

        // 1. CORREZIONE: Cambiato in *0..50 per includere l'esperimento stesso
        OPTIONAL MATCH (e)-[:USES_MODEL]->(direct_model:Model)
        CALL {{
            WITH e
            MATCH path = (e)-[:DERIVED_FROM|RETRY_OF|RESUMED_FROM*0..50]->(ancestor:Experiment)-[:USES_MODEL]->(inherited_model:Model)
            RETURN inherited_model
            ORDER BY length(path) ASC
            LIMIT 1
        }}
        WITH e, COALESCE(direct_model, inherited_model) AS resolved_model

        // 2. CORREZIONE: Cambiato in *0..50 per includere l'esperimento stesso
        OPTIONAL MATCH (e)-[:USES_RECIPE]->(direct_recipe:Recipe)
        CALL {{
            WITH e
            MATCH path = (e)-[:DERIVED_FROM|RETRY_OF|RESUMED_FROM*0..50]->(ancestor:Experiment)-[:USES_RECIPE]->(inherited_recipe:Recipe)
            RETURN inherited_recipe
            ORDER BY length(path) ASC
            LIMIT 1
        }}
        WITH e, resolved_model, COALESCE(direct_recipe, inherited_recipe) AS resolved_recipe

        // 3. CORREZIONE: Cambiato in *0..50 per includere l'esperimento stesso
        OPTIONAL MATCH (e)-[:USES_COMPONENT]->(direct_comp:Component)
        CALL {{
            WITH e
            MATCH path = (e)-[:DERIVED_FROM|RETRY_OF|RESUMED_FROM*0..50]->(ancestor:Experiment)-[:USES_COMPONENT]->(inherited_comp:Component)
            RETURN inherited_comp
            ORDER BY length(path) ASC
            LIMIT 1
        }}
        WITH e, resolved_model, resolved_recipe, COALESCE(direct_comp, inherited_comp) AS resolved_comp

        OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)

        // Raggruppiamo passando 'e' e il conteggio
        WITH e, resolved_model, resolved_recipe, resolved_comp, COUNT(ckp) AS ckp_count

        // 4. Mettiamo tutte le proprietà estruse DENTRO il dizionario del nodo 'e'
        RETURN e {{.*,
            model_name: resolved_model.model_name,
            model_id: resolved_model.id,
            model_uri: resolved_model.uri,
            recipe_name: resolved_recipe.name,
            recipe_id: resolved_recipe.id,
            component_technique: resolved_comp.technique_code,
            component_framework: resolved_comp.framework_code,
            component_id: resolved_comp.id,
            ckp_count: ckp_count
        }} AS node
        ORDER BY node.created_at DESC
        LIMIT 100
        """
        results = await self.db.run_list(query, **params)
        return [_row_to_experiment(r["node"]) for r in results]
    
   