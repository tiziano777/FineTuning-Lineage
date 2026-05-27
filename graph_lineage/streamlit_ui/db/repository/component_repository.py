"""Repository for Component entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)

_SETUPS_PREFIX = "./graph_lineage/setups/"

# Columns returned by every SELECT query
_RETURN_COLS = """
    c.id as id, c.name as name, c.uri as uri,
    c.opt_code as opt_code, c.technique_code as technique_code,
    c.framework_code as framework_code,
    c.docs_url as docs_url, c.description as description,
    c.created_at as created_at, c.updated_at as updated_at
"""


class ComponentRepository:
    """Data access layer for Component entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    async def create(
        self,
        component_id: str,
        name: str,
        technique_code: str,
        framework_code: str,
        opt_code: str = "",
        uri: str = "",
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Create a new component.

        Args:
            component_id: Unique component ID.
            name: Component name (= setup template folder name, e.g. "dpo_trl").
            technique_code: Technique code.
            framework_code: Framework code.
            opt_code: Optimization code.
            uri: Internal URI to setup template. Auto-derived from name if empty.
            docs_url: Documentation URL.
            description: Component description.

        Returns:
            Created component data.
        """
        resolved_uri = uri if uri else f"{_SETUPS_PREFIX}{name}"
        now = datetime.utcnow().isoformat()

        query = f"""
        CREATE (c:Component {{
            id: $id,
            name: $name,
            uri: $uri,
            opt_code: $opt_code,
            technique_code: $technique_code,
            framework_code: $framework_code,
            docs_url: $docs_url,
            description: $description,
            created_at: $created_at,
            updated_at: $updated_at
        }})
        RETURN {_RETURN_COLS}
        """

        result = await self.db.run_single(
            query,
            id=component_id,
            name=name,
            uri=resolved_uri,
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

        logger.info(f"Component created: id={component_id}, name={name}, technique={technique_code}")
        return result

    async def create_component(
        self,
        name: str,
        opt_code: str,
        technique_code: str,
        framework_code: str,
        uri: str = "",
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Create a new component (generates UUID automatically).

        Args:
            name: Component name (= setup template folder name).
            opt_code: Optimization code.
            technique_code: Technique code (e.g., lora_grpo).
            framework_code: Framework code (e.g., unsloth).
            uri: Internal URI. Auto-derived from name if empty.
            docs_url: Documentation URL.
            description: Component description.

        Returns:
            Created component data.
        """
        import uuid
        component_id = str(uuid.uuid4())
        return await self.create(
            component_id=component_id,
            name=name,
            technique_code=technique_code,
            framework_code=framework_code,
            opt_code=opt_code,
            uri=uri,
            docs_url=docs_url,
            description=description,
        )

    async def get_by_id(self, component_id: str) -> Optional[dict]:
        """Get component by ID."""
        query = f"""
        MATCH (c:Component {{id: $id}})
        RETURN {_RETURN_COLS}
        """
        return await self.db.run_single(query, id=component_id)

    async def list_all(self) -> list[dict]:
        """List all components."""
        query = f"""
        MATCH (c:Component)
        RETURN {_RETURN_COLS}
        LIMIT 100
        """
        return await self.db.run_list(query)

    async def list_components(self) -> list[dict]:
        """Alias for list_all for manager compatibility."""
        return await self.list_all()

    async def get_component(self, component_id: str) -> Optional[dict]:
        """Alias for get_by_id for manager compatibility."""
        return await self.get_by_id(component_id)

    async def update_component(
        self,
        component_id: str,
        name: str = "",
        uri: str = "",
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Alias for update for manager compatibility."""
        return await self.update(
            component_id=component_id,
            name=name,
            uri=uri,
            docs_url=docs_url,
            description=description,
        )

    async def delete_component(self, component_id: str) -> None:
        """Alias for delete for manager compatibility."""
        await self.delete(component_id)

    async def check_component_dependencies(self, component_id: str) -> int:
        """Alias for count_dependencies for manager compatibility."""
        return await self.count_dependencies(component_id)

    async def update(
        self,
        component_id: str,
        name: str = "",
        uri: str = "",
        docs_url: str = "",
        description: str = "",
    ) -> dict:
        """Update component fields.

        If name is provided and uri is empty, uri is re-derived from name.

        Args:
            component_id: Component ID.
            name: New component name (updates uri too if uri is empty).
            uri: Explicit URI override. If empty and name given, auto-derived.
            docs_url: New documentation URL.
            description: New description.

        Returns:
            Updated component data.
        """
        now = datetime.utcnow().isoformat()

        # Fetch current values for fields not being updated
        existing = await self.get_by_id(component_id)
        if not existing:
            raise UIError(f"Component {component_id} not found")

        new_name = name if name else existing.get("name", "")
        if uri:
            new_uri = uri
        elif name:
            new_uri = f"{_SETUPS_PREFIX}{new_name}"
        else:
            new_uri = existing.get("uri", "")

        query = f"""
        MATCH (c:Component {{id: $id}})
        SET c.name = $name, c.uri = $uri,
            c.docs_url = $docs_url, c.description = $description,
            c.updated_at = $updated_at
        RETURN {_RETURN_COLS}
        """

        result = await self.db.run_single(
            query,
            id=component_id,
            name=new_name,
            uri=new_uri,
            docs_url=docs_url,
            description=description,
            updated_at=now,
        )

        if not result:
            raise UIError(f"Component {component_id} not found")

        logger.info(f"Component updated: id={component_id}")
        return result

    async def delete(self, component_id: str) -> None:
        """Delete component with constraint checking."""
        existing = await self.get_by_id(component_id)
        if not existing:
            raise UIError(f"Component '{component_id}' not found")

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
        """Check if component can be deleted (no related experiments)."""
        existing = await self.get_by_id(component_id)
        if not existing:
            return True
        query = """
        MATCH (c:Component {id: $id})
        OPTIONAL MATCH (c)<-[:USED_FOR]-(e:Experiment)
        RETURN COUNT(e) as experiment_count
        """
        result = await self.db.run_single(query, id=component_id)
        if result:
            return result.get("experiment_count", 0) == 0
        return True

    async def count_dependencies(self, component_id: str) -> int:
        """Count relationships to this component."""
        return await self.db.count_relationships(component_id, "Component")
