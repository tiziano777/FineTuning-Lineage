"""Repository for Model entity - Neo4j data access layer."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class ModelRepository:
    """Data access layer for Model entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    async def create(
        self,
        model_id: str,
        model_name: str,
        version: str = "",
        uri: str = "",
        url: str = "",
        doc_url: str = "",
        description: str = "",
    ) -> dict:
        """Create a new model.

        Args:
            model_id: Unique model ID.
            model_name: Unique model name.
            version: Model version.
            uri: Model URI.
            url: Model URL.
            doc_url: Documentation URL.
            description: Model description.

        Returns:
            Created model data.
        """
        now = datetime.utcnow().isoformat()
        query = """
        CREATE (m:Model {
            id: $id,
            model_name: $model_name,
            version: $version,
            uri: $uri,
            url: $url,
            doc_url: $doc_url,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at
        })
        RETURN m.id as id, m.model_name as model_name, m.version as version,
               m.uri as uri, m.url as url, m.doc_url as doc_url,
               m.description as description, m.created_at as created_at, m.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=model_id,
            model_name=model_name,
            version=version,
            uri=uri,
            url=url,
            doc_url=doc_url,
            description=description,
            created_at=now,
            updated_at=now,
        )

        if not result:
            raise UIError("Failed to create model in Neo4j")

        logger.info(f"Model created: id={model_id}, name={model_name}")
        return result

    async def create_model(
        self,
        model_name: str,
        version: str = "",
        uri: str = "",
        url: str = "",
        doc_url: str = "",
        description: str = "",
    ) -> dict:
        """Create a new model (generates UUID automatically).

        Args:
            model_name: Unique model name.
            version: Model version.
            uri: Model URI.
            url: Model URL.
            doc_url: Documentation URL.
            description: Model description.

        Returns:
            Created model data.
        """
        import uuid
        model_id = str(uuid.uuid4())
        return await self.create(
            model_id=model_id,
            model_name=model_name,
            version=version,
            uri=uri,
            url=url,
            doc_url=doc_url,
            description=description,
        )

    async def get_by_id(self, model_id: str) -> Optional[dict]:
        """Get model by ID.

        Args:
            model_id: Model ID.

        Returns:
            Model data or None if not found.
        """
        query = """
        MATCH (m:Model {id: $id})
        RETURN m.id as id, m.model_name as model_name, m.version as version,
               m.uri as uri, m.url as url, m.doc_url as doc_url,
               m.description as description, m.created_at as created_at, m.updated_at as updated_at
        """

        result = await self.db.run_single(query, id=model_id)
        return result

    async def list_all(self) -> list[dict]:
        """List all models.

        Returns:
            List of model dictionaries.
        """
        query = """
        MATCH (m:Model)
        RETURN m.id as id, m.model_name as model_name, m.version as version,
               m.uri as uri, m.url as url, m.doc_url as doc_url,
               m.description as description, m.created_at as created_at, m.updated_at as updated_at
        LIMIT 100
        """

        results = await self.db.run_list(query)
        return results

    async def list_models(self) -> list[dict]:
        """Alias for list_all for manager compatibility.

        Returns:
            List of model dictionaries.
        """
        return await self.list_all()

    async def get_model(self, model_id: str) -> Optional[dict]:
        """Alias for get_by_id for manager compatibility.

        Args:
            model_id: Model ID.

        Returns:
            Model data or None if not found.
        """
        return await self.get_by_id(model_id)

    async def update_model(
        self,
        model_id: str,
        version: str = "",
        uri: str = "",
        url: str = "",
        doc_url: str = "",
        description: str = "",
    ) -> dict:
        """Alias for update for manager compatibility."""
        return await self.update(
            model_id=model_id,
            version=version,
            uri=uri,
            url=url,
            doc_url=doc_url,
            description=description,
        )

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

    async def upsert_by_name(
        self,
        model_name: str,
        version: str = "",
        url: str = "",
        doc_url: str = "",
        description: str = "",
    ) -> dict:
        """Upsert model by model_name using MERGE semantics.

        Creates the model if no model with model_name exists,
        otherwise updates non-empty fields on the existing model.

        Args:
            model_name: Unique model name (merge key).
            version: Model version.
            url: Model URL.
            doc_url: Documentation URL.
            description: Model description.

        Returns:
            Upserted model data.
        """
        now = datetime.utcnow().isoformat()
        model_id = str(uuid.uuid4())
        query = """
        MERGE (m:Model {model_name: $model_name})
        ON CREATE SET m.id = $id, m.version = $version, m.url = $url,
                      m.doc_url = $doc_url, m.description = $description,
                      m.created_at = $created_at, m.updated_at = $updated_at
        ON MATCH SET m.version = CASE WHEN $version <> '' THEN $version ELSE m.version END,
                     m.url = CASE WHEN $url <> '' THEN $url ELSE m.url END,
                     m.doc_url = CASE WHEN $doc_url <> '' THEN $doc_url ELSE m.doc_url END,
                     m.description = CASE WHEN $description <> '' THEN $description ELSE m.description END,
                     m.updated_at = $updated_at
        RETURN m.id as id, m.model_name as model_name, m.version as version,
               m.url as url, m.doc_url as doc_url, m.description as description,
               m.created_at as created_at, m.updated_at as updated_at
        """
        result = await self.db.run_single(
            query,
            id=model_id,
            model_name=model_name,
            version=version,
            url=url,
            doc_url=doc_url,
            description=description,
            created_at=now,
            updated_at=now,
        )
        if not result:
            raise UIError("Failed to upsert model")
        logger.info(f"Model upserted: name={model_name}")
        return dict(result)

    async def update(
        self,
        model_id: str,
        version: str = "",
        uri: str = "",
        url: str = "",
        doc_url: str = "",
        description: str = "",
    ) -> dict:
        """Update model fields.

        Args:
            model_id: Model ID.
            version: New version.
            uri: New URI.
            url: New URL.
            doc_url: New documentation URL.
            description: New description.

        Returns:
            Updated model data.
        """
        now = datetime.utcnow().isoformat()

        query = """
        MATCH (m:Model {id: $id})
        SET m.version = $version, m.uri = $uri, m.url = $url,
            m.doc_url = $doc_url, m.description = $description,
            m.updated_at = $updated_at
        RETURN m.id as id, m.model_name as model_name, m.version as version,
               m.uri as uri, m.url as url, m.doc_url as doc_url,
               m.description as description, m.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=model_id,
            version=version,
            uri=uri,
            url=url,
            doc_url=doc_url,
            description=description,
            updated_at=now,
        )

        if not result:
            raise UIError(f"Model {model_id} not found")

        logger.info(f"Model updated: id={model_id}")
        return result

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
