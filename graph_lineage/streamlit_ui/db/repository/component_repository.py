"""Repository for Component entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class ComponentRepository:
    """Data access layer for Component entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    async def create(
        self,
        component_id: str,
        technique_code: str,
        framework_code: str,
        opt_code: str = "",
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Create a new component.

        Args:
            component_id: Unique component ID.
            technique_code: Technique code.
            framework_code: Framework code.
            opt_code: Optimization code.
            docs_url: Documentation URL.
            description: Component description.

        Returns:
            Created component data.
        """
        component_id_val = component_id
        now = datetime.utcnow().isoformat()

        query = """
        CREATE (c:Component {
            id: $id,
            opt_code: $opt_code,
            technique_code: $technique_code,
            framework_code: $framework_code,
            docs_url: $docs_url,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at
        })
        RETURN c.id as id, c.opt_code as opt_code, c.technique_code as technique_code,
               c.framework_code as framework_code, c.docs_url as docs_url,
               c.description as description, c.created_at as created_at, c.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=component_id_val,
            opt_code=opt_code,
            technique_code=technique_code,
            framework_code=framework_code,
            docs_url=docs_url,
            description=description,
            created_at=now,
            updated_at=now,
        )

        if not result:
            raise UIError("Failed to create component in Neo4j")

        logger.info(f"Component created: id={component_id_val}, technique={technique_code}")
        return result

    async def create_component(
        self,
        opt_code: str,
        technique_code: str,
        framework_code: str,
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Create a new component (generates UUID automatically).

        Args:
            opt_code: Optimization code.
            technique_code: Technique code (e.g., lora_grpo).
            framework_code: Framework code (e.g., unsloth).
            docs_url: Documentation URL.
            description: Component description.

        Returns:
            Created component data.
        """
        import uuid
        component_id = str(uuid.uuid4())
        return await self.create(
            component_id=component_id,
            technique_code=technique_code,
            framework_code=framework_code,
            opt_code=opt_code,
            docs_url=docs_url,
            description=description,
        )

    async def get_by_id(self, component_id: str) -> Optional[dict]:
        """Get component by ID.

        Args:
            component_id: Component ID.

        Returns:
            Component data or None if not found.
        """
        query = """
        MATCH (c:Component {id: $id})
        RETURN c.id as id, c.opt_code as opt_code, c.technique_code as technique_code,
               c.framework_code as framework_code, c.docs_url as docs_url,
               c.description as description, c.created_at as created_at, c.updated_at as updated_at
        """

        result = await self.db.run_single(query, id=component_id)
        return result

    async def list_all(self) -> list[dict]:
        """List all components.

        Returns:
            List of component dictionaries.
        """
        query = """
        MATCH (c:Component)
        RETURN c.id as id, c.opt_code as opt_code, c.technique_code as technique_code,
               c.framework_code as framework_code, c.docs_url as docs_url,
               c.description as description, c.created_at as created_at, c.updated_at as updated_at
        LIMIT 100
        """

        results = await self.db.run_list(query)
        return results

    async def list_components(self) -> list[dict]:
        """Alias for list_all for manager compatibility.

        Returns:
            List of component dictionaries.
        """
        return await self.list_all()

    async def get_component(self, component_id: str) -> Optional[dict]:
        """Alias for get_by_id for manager compatibility.

        Args:
            component_id: Component ID.

        Returns:
            Component data or None if not found.
        """
        return await self.get_by_id(component_id)

    async def update_component(
        self,
        component_id: str,
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Alias for update for manager compatibility."""
        return await self.update(
            component_id=component_id,
            docs_url=docs_url,
            description=description,
        )

    async def delete_component(self, component_id: str) -> None:
        """Alias for delete for manager compatibility.

        Args:
            component_id: Component ID to delete.
        """
        await self.delete(component_id)

    async def check_component_dependencies(self, component_id: str) -> int:
        """Alias for count_dependencies for manager compatibility.

        Args:
            component_id: Component ID.

        Returns:
            Number of dependent relationships.
        """
        return await self.count_dependencies(component_id)

    async def update(
        self,
        component_id: str,
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Update component fields.

        Args:
            component_id: Component ID.
            docs_url: New documentation URL.
            description: New description.

        Returns:
            Updated component data.
        """
        now = datetime.utcnow().isoformat()

        query = """
        MATCH (c:Component {id: $id})
        SET c.docs_url = $docs_url, c.description = $description, c.updated_at = $updated_at
        RETURN c.id as id, c.opt_code as opt_code, c.technique_code as technique_code,
               c.framework_code as framework_code, c.docs_url as docs_url,
               c.description as description, c.updated_at as updated_at
        """

        result = await self.db.run_single(
            query,
            id=component_id,
            docs_url=docs_url,
            description=description,
            updated_at=now,
        )

        if not result:
            raise UIError(f"Component {component_id} not found")

        logger.info(f"Component updated: id={component_id}")
        return result

    async def delete(self, component_id: str) -> None:
        """Delete component with constraint checking.

        Args:
            component_id: Component ID to delete.

        Raises:
            UIError: If component not found, has related experiments, or query fails.
        """
        existing = await self.get_by_id(component_id)
        if not existing:
            raise UIError(f"Component '{component_id}' not found")

        # Check if component can be deleted (no related experiments)
        if not await self.is_deletable(component_id):
            raise UIError(
                f"Cannot delete component '{component_id}': it's used by one or more experiments. "
                "Remove experiments first before deleting the component."
            )

        try:
            query = "MATCH (c:Component {id: $id}) DETACH DELETE c"
            await self.db.run(query, id=component_id)
            logger.warning(f"Component deleted: id={component_id}")
        except Exception as e:
            logger.error(f"Component deletion failed: {component_id}", exc_info=True)
            raise UIError(f"Failed to delete component: {str(e)}")

    async def is_deletable(self, component_id: str) -> bool:
        """Check if component can be deleted (no related experiments).

        Args:
            component_id: Component ID to check.

        Returns:
            True if component has no related experiments, False otherwise.
        """
        existing = await self.get_by_id(component_id)
        if not existing:
            return True
        # Query for experiments using this component
        query = """
        MATCH (c:Component {id: $id})
        OPTIONAL MATCH (c)<-[:USED_FOR]-(e:Experiment)
        RETURN COUNT(e) as experiment_count
        """
        result = await self.db.run_single(query, id=component_id)
        if result:
            count = result.get("experiment_count", 0)
            return count == 0
        return True

    async def count_dependencies(self, component_id: str) -> int:
        """Count relationships to this component.

        Args:
            component_id: Component ID.

        Returns:
            Number of dependent relationships.
        """
        return await self.db.count_relationships(component_id, "Component")
