"""Repository for Model entity - Neo4j data access layer."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Dict

from graph_lineage.data_classes.neo4j.nodes.model import Model, ModelType
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.neo4j_client.client import StreamlitNeo4jClient

logger = logging.getLogger(__name__)

class ModelRepository:
    """Data access layer for Model entity.

    Works directly with Model pydantic instances, preserving extra fields
    via the ConfigDict(extra='allow') configuration on BaseEntity.
    """

    def __init__(self, db_client: StreamlitNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    def _model_to_db_params(self, model: Model, include_timestamps: bool = True) -> Dict[str, Any]:
        """Convert Model instance to flat dict for Neo4j query parameters.

        Handles both defined fields and extra/custom fields uniformly.
        Pydantic extra fields are merged at the top level with standard fields.
        """
        # Start with model dump - includes all defined + extra fields
        data = model.model_dump(exclude={'id', 'created_at', 'updated_at'} if not include_timestamps else set())

        # Ensure kind is stored as string value, not enum object
        if isinstance(data.get('kind'), ModelType):
            data['kind'] = data['kind'].value

        # Add core fields back if needed
        if include_timestamps:
            data['id'] = model.id
            data['created_at'] = model.created_at.isoformat() if hasattr(model.created_at, 'isoformat') else str(model.created_at)
            data['updated_at'] = model.updated_at.isoformat() if hasattr(model.updated_at, 'isoformat') else str(model.updated_at)
        else:
            data['id'] = model.id

        return data

    def _row_to_model(self, row: Dict[str, Any]) -> Model:
        """Convert Neo4j result row back to Model instance.

        Extra fields in the row that are not part of the Model schema
        will be preserved thanks to ConfigDict(extra='allow').
        """
        if not row:
            raise UIError("Empty row cannot be converted to Model")

        data = dict(row)

        if 'kind' in data and isinstance(data['kind'], str):
            try:
                data['kind'] = ModelType(data['kind'])
            except ValueError:
                data['kind'] = ModelType.UNKNOWN

        return Model(**data)

    async def _create(self, model: Model) -> Model:
        """Create a new model from a Model instance.

        Args:
            model: Complete Model instance with all fields (standard + custom).

        Returns:
            Created model data as Model instance.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Build dynamic property map from model data
        params = self._model_to_db_params(model, include_timestamps=False)

        # Generate property placeholders dynamically to support extra fields
        prop_keys = list(params.keys())
        prop_map = ', '.join([f"{k}: ${k}" for k in prop_keys])

        query = f"""
        CREATE (m:Model {{{prop_map}}})
        RETURN m
        """

        result = await self.db.run_single(query, **params)

        if not result or 'm' not in result:
            raise UIError("Failed to create model in Neo4j")

        logger.info(f"Model created: id={model.id}, name={model.model_name}")
        return self._row_to_model(result['m'])

    async def create_model(self, model: Model) -> Model:
        """Create a new model (assigns UUID if not provided).

        Args:
            model: Model instance. If id is empty, a new UUID is generated.

        Returns:
            Created model data as Model instance.
        """
        if not model.id:
            model.id = str(uuid.uuid4())
        return await self._create(model)

    async def get_by_id(self, model_id: str) -> Optional[Model]:
        """Get model by ID.

        Args:
            model_id: Model ID.

        Returns:
            Model object or None if not found.
        """
        query = """
        MATCH (m:Model {id: $id})
        RETURN m
        """

        result = await self.db.run_single(query, id=model_id)
        if not result or 'm' not in result:
            return None
        return self._row_to_model(result['m'])

    async def list_all(self) -> list[Model]:
        """List all models with default limit of 100.

        Returns:
            List of Model objects.
        """
        return await self.list_with_limit(limit=100, offset=0)

    async def list_with_limit(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Model]:
        """List models with pagination support.

        Args:
            limit: Maximum number of models to return.
            offset: Number of models to skip (for pagination).

        Returns:
            List of Model objects.
        """
        query = """
        MATCH (m:Model)
        RETURN m
        ORDER BY m.created_at DESC
        SKIP $offset LIMIT $limit
        """
        results = await self.db.run_list(query, limit=limit, offset=offset)
        return [self._row_to_model(row['m']) for row in results if 'm' in row]

    async def list_models(self) -> list[Model]:
        """Alias for list_all for manager compatibility.

        Returns:
            List of Model objects.
        """
        return await self.list_all()

    async def get_model(self, model_id: str) -> Optional[Model]:
        """Alias for get_by_id for manager compatibility.

        Args:
            model_id: Model ID.

        Returns:
            Model object or None if not found.
        """
        return await self.get_by_id(model_id)

    async def update_model(self, model: Model) -> Model:
        """Update model from a Model instance.

        Preserves existing fields not present in the update, and handles
        extra/custom fields dynamically.

        Args:
            model: Model instance with updated fields. Must have valid id.

        Returns:
            Updated model data as Model instance.
        """
        if not model.id:
            raise UIError("Model id is required for update")

        now = datetime.now(timezone.utc).isoformat()

        # Build dynamic SET clauses for all fields present in the model
        # This ensures extra fields are also updated
        data = model.model_dump(exclude={'id', 'created_at'})
        data['updated_at'] = now

        # Ensure kind is string
        if isinstance(data.get('kind'), ModelType):
            data['kind'] = data['kind'].value

        set_clauses = []
        for key in data.keys():
            set_clauses.append(f"m.{key} = ${key}")

        set_statement = ', '.join(set_clauses)

        query = f"""
        MATCH (m:Model {{id: $id}})
        SET {set_statement}
        RETURN m
        """

        params = {'id': model.id, **data}

        result = await self.db.run_single(query, **params)

        if not result or 'm' not in result:
            raise UIError(f"Model {model.id} not found")

        logger.info(f"Model updated: id={model.id}")
        return self._row_to_model(result['m'])

    async def delete_model(self, model_id: str) -> None:
        """Alias for delete for manager compatibility.

        Args:
            model_id: Model ID to delete.
        """
        await self.delete(model_id)

    async def check_model_dependencies(self, model_id: str) -> int:
        """Alias for count_dependencies for manager compatibility.

        Args:
            model_id: Model ID.

        Returns:
            Number of dependent relationships.
        """
        return await self.count_dependencies(model_id)

    async def upsert_by_name(self, model: Model) -> Model:
        """Upsert model by model_name using MERGE semantics.

        Creates the model if no model with model_name exists,
        otherwise updates non-empty fields on the existing model.
        Preserves extra/custom fields during updates.

        Args:
            model: Model instance with model_name as merge key.

        Returns:
            Upserted model data as Model instance.
        """
        if not model.model_name:
            raise UIError("model_name is required for upsert")

        now = datetime.now(timezone.utc).isoformat()

        if not model.id:
            model.id = str(uuid.uuid4())

        # Build dynamic ON CREATE and ON MATCH sets
        data = model.model_dump(exclude={'model_name'})

        # Ensure kind is string
        if isinstance(data.get('kind'), ModelType):
            data['kind'] = data['kind'].value

        # Remove empty values for conditional update logic
        create_fields = []
        match_fields = []

        for key, value in data.items():
            if key in ('created_at', 'updated_at'):
                continue
            create_fields.append(f"m.{key} = ${key}")

            # For match: only update if value is meaningful (not empty string, not None for kind)
            if key == 'kind':
                match_fields.append(f"m.{key} = CASE WHEN ${key} IS NOT NULL THEN ${key} ELSE m.{key} END")
            elif isinstance(value, str):
                match_fields.append(f"m.{key} = CASE WHEN ${key} <> '' THEN ${key} ELSE m.{key} END")
            else:
                match_fields.append(f"m.{key} = CASE WHEN ${key} IS NOT NULL THEN ${key} ELSE m.{key} END")

        create_set = ', '.join(create_fields) if create_fields else ''
        match_set = ', '.join(match_fields) if match_fields else ''

        query = f"""
        MERGE (m:Model {{model_name: $model_name}})
        ON CREATE SET m.created_at = $created_at, m.updated_at = $updated_at{', ' + create_set if create_set else ''}
        ON MATCH SET m.updated_at = $updated_at{', ' + match_set if match_set else ''}
        RETURN m
        """

        params = {
            'model_name': model.model_name,
            'created_at': now,
            'updated_at': now,
            **{k: v for k, v in data.items() if k not in ('created_at', 'updated_at')}
        }

        result = await self.db.run_single(query, **params)
        if not result or 'm' not in result:
            raise UIError("Failed to upsert model")
        logger.info(f"Model upserted: name={model.model_name}")
        return self._row_to_model(result['m'])

    async def update(
        self,
        model_id: str,
        version: str = "",
        uri: str = "",
        url: str = "",
        doc_url: str = "",
        description: str = "",
        kind: Optional[ModelType] = None,
        architecture_info_ref: str = "",
        **extra_fields: Any,
    ) -> Model:
        """Update model fields (legacy signature with extra fields support).

        Args:
            model_id: Model ID.
            version: New version.
            uri: New URI.
            url: New URL.
            doc_url: New documentation URL.
            description: New description.
            kind: New model kind.
            architecture_info_ref: New reference to architecture document.
            **extra_fields: Additional custom fields to update.

        Returns:
            Updated model data as Model instance.
        """
        model = Model(
            id=model_id,
            model_name="",  # Will be preserved by update logic
            version=version,
            uri=uri,
            url=url,
            doc_url=doc_url,
            description=description,
            kind=kind or ModelType.UNKNOWN,
            architecture_info_ref=architecture_info_ref,
            **extra_fields
        )
        return await self.update_model(model)

    async def delete(self, model_id: str) -> None:
        """Delete model with constraint checking.

        Args:
            model_id: Model ID to delete.

        Raises:
            UIError: If model not found, has related experiments, or query fails.
        """
        existing = await self.get_by_id(model_id)
        if not existing:
            raise UIError(f"Model '{model_id}' not found")

        # Check if model can be deleted (no related experiments)
        if not await self.is_deletable(model_id):
            raise UIError(
                f"Cannot delete model '{model_id}': it's used by one or more experiments. "
                "Remove experiments first before deleting the model."
            )

        try:
            query = "MATCH (m:Model {id: $id}) DETACH DELETE m"
            await self.db.run(query, id=model_id)
            logger.warning(f"Model deleted: id={model_id}")
        except Exception as e:
            logger.error(f"Model deletion failed: {model_id}", exc_info=True)
            raise UIError(f"Failed to delete model: {str(e)}")

    async def is_deletable(self, model_id: str) -> bool:
        """Check if model can be deleted.

        Model cannot be deleted if:
        - It has outgoing SELECTED_FOR relationships (used in experiments)
        - It has outgoing MERGED_FROM relationships (used as base for model merging)

        Args:
            model_id: Model ID to check.

        Returns:
            True if model has no blocking relationships, False otherwise.
        """
        existing = await self.get_by_id(model_id)
        if not existing:
            return True

        # Query for blocking outgoing relationships
        query = """
        MATCH (m:Model {id: $id})
        OPTIONAL MATCH (m)-[:SELECTED_FOR]->(e:Experiment)
        OPTIONAL MATCH (m)-[:MERGED_FROM]->(m2:Model)
        RETURN COUNT(e) as selected_count, COUNT(m2) as merged_count
        """
        result = await self.db.run_single(query, id=model_id)
        if result:
            selected_count = result.get("selected_count", 0)
            merged_count = result.get("merged_count", 0)
            return selected_count == 0 and merged_count == 0
        return True

    async def count_dependencies(self, model_id: str) -> int:
        """Count relationships to this model.

        Args:
            model_id: Model ID.

        Returns:
            Number of dependent relationships.
        """
        return await self.db.count_relationships(model_id, "Model")
   