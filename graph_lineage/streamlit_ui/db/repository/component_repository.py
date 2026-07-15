"""Repository for Component entity - Neo4j data access layer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any

from graph_lineage.data_classes.neo4j.nodes.component import Component
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.neo4j_client.client import StreamlitNeo4jClient

logger = logging.getLogger(__name__)

_SETUPS_PREFIX = "./graph_lineage/setups/"

# Standard fields known to the Component model
_STANDARD_FIELDS = {
    "id", "name", "uri", "opt_code", "technique_code",
    "framework_code", "docs_url", "description",
    "created_at", "updated_at",
}


class ComponentRepository:
    """Data access layer for Component entity.

    Supports dynamic extra fields via Pydantic ConfigDict(extra='allow').
    All CRUD operations preserve custom fields stored in Neo4j.
    No APOC triggers required — extra fields are handled natively
    by Pydantic which merges them at the top level automatically.
    """

    def __init__(self, db_client: StreamlitNeo4jClient):
        """Initialize repository with Neo4j client."""
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    # ─────────────────────────────────────────────────────────────────────
    # Helper: build property map from Component instance
    # ─────────────────────────────────────────────────────────────────────

    def _component_to_props(self, component: Component) -> dict[str, Any]:
        """Serialize a Component instance into a flat dict for Neo4j.

        Includes both standard fields and custom extra fields.
        Pydantic's model_dump() automatically includes extra fields
        thanks to ConfigDict(extra='allow').
        """
        props = component.model_dump(mode="json", exclude_none=False)
        # Ensure timestamps are ISO strings
        for ts_field in ("created_at", "updated_at"):
            val = props.get(ts_field)
            if isinstance(val, datetime):
                props[ts_field] = val.isoformat()
        return props

    def _record_to_component(self, record: dict | None) -> Component | None:
        """Convert a Neo4j record dict into a Component instance.

        Pydantic's extra='allow' automatically absorbs any extra keys
        at the top level — no manual merging needed!
        """
        if not record:
            return None
        return Component(**record)

    def _build_dynamic_set(self, props: dict[str, Any], alias: str = "c") -> str:
        """Build a dynamic SET clause from a flat property dict.

        Sanitizes keys to prevent Cypher injection.
        """
        lines = []
        for key in props.keys():
            safe_key = key.replace("`", "``")
            lines.append(f"{alias}.`{safe_key}` = ${key}")
        return ",\n            ".join(lines)

    # ─────────────────────────────────────────────────────────────────────
    # CRUD Operations
    # ─────────────────────────────────────────────────────────────────────

    async def create(self, component: Component) -> Component:
        """Create a new component from a Component instance.

        Args:
            component: Fully populated Component instance (including extras).

        Returns:
            Created Component with all fields (including extras).
        """
        # Auto-resolve URI if empty
        if not component.uri and component.name:
            component.uri = f"{_SETUPS_PREFIX}{component.name}"

        # Ensure timestamps
        now = datetime.now(timezone.utc)
        if not component.created_at:
            component.created_at = now
        if not component.updated_at:
            component.updated_at = now

        props = self._component_to_props(component)
        set_clause = self._build_dynamic_set(props)

        query = f"""
        CREATE (c:Component)
        SET {set_clause}
        RETURN c {{.*}} as c
        """

        result = await self.db.run_single(query, **props)

        if not result or "c" not in result:
            raise UIError("Failed to create component in Neo4j")

        created = self._record_to_component(result["c"])
        logger.info(f"Component created: id={created.id}, name={created.name}")
        return created

    async def create_from_params(
        self,
        name: str,
        technique_code: str,
        framework_code: str,
        opt_code: str = "",
        uri: str = "",
        docs_url: str = "",
        description: str = "",
        **extra_fields: Any,
    ) -> Component:
        """Convenience factory: create Component from individual params + extras.

        Args:
            name, technique_code, framework_code: Required fields.
            opt_code, uri, docs_url, description: Optional standard fields.
            **extra_fields: Any additional custom metadata fields.

        Returns:
            Created Component instance.
        """
        component = Component(
            name=name,
            technique_code=technique_code,
            framework_code=framework_code,
            opt_code=opt_code,
            uri=uri,
            docs_url=docs_url,
            description=description,
            **extra_fields,
        )
        return await self.create(component)

    async def get_by_id(self, component_id: str) -> Optional[Component]:
        """Get component by ID. Returns Component or None."""
        query = """
        MATCH (c:Component {id: $id})
        RETURN c {.*} as c
        """
        result = await self.db.run_single(query, id=component_id)
        return self._record_to_component(result.get("c") if result else None)

    async def list_all(self) -> list[Component]:
        """List all components with default limit of 100."""
        return await self.list_with_limit(limit=100, offset=0)

    async def list_with_limit(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Component]:
        """List components with pagination support."""
        query = """
        MATCH (c:Component)
        RETURN c {.*} as c
        ORDER BY c.created_at DESC
        SKIP $offset LIMIT $limit
        """
        results = await self.db.run_list(query, limit=limit, offset=offset)
        return [self._record_to_component(r["c"]) for r in results if "c" in r]

    # ─────────────────────────────────────────────────────────────────────
    # Alias methods for manager compatibility
    # ─────────────────────────────────────────────────────────────────────

    async def list_components(self) -> list[Component]:
        """Alias for list_all."""
        return await self.list_all()

    async def get_component(self, component_id: str) -> Optional[Component]:
        """Alias for get_by_id."""
        return await self.get_by_id(component_id)

    # ─────────────────────────────────────────────────────────────────────
    # Update
    # ─────────────────────────────────────────────────────────────────────

    async def update(
        self,
        component_id: str,
        name: str = "",
        uri: str = "",
        docs_url: str = "",
        description: str = "",
        **extra_fields: Any,
    ) -> Component:
        """Update component fields.

        If name is provided and uri is empty, uri is re-derived from name.
        Any extra_fields are merged into the node (create or overwrite).

        Args:
            component_id: Component ID.
            name, uri, docs_url, description: Standard fields to update.
            **extra_fields: Additional custom metadata to set/update.

        Returns:
            Updated Component instance with all fields.
        """
        existing = await self.get_by_id(component_id)
        if not existing:
            raise UIError(f"Component {component_id} not found")

        new_name = name if name else existing.name
        if uri:
            new_uri = uri
        elif name:
            new_uri = f"{_SETUPS_PREFIX}{new_name}"
        else:
            new_uri = existing.uri

        now = datetime.now(timezone.utc).isoformat()

        # Build props dict for all fields to set
        props = {
            "id": component_id,
            "name": new_name,
            "uri": new_uri,
            "docs_url": docs_url,
            "description": description,
            "updated_at": now,
        }

        # Merge extra fields
        props.update(extra_fields)

        set_clause = self._build_dynamic_set(props)

        query = f"""
        MATCH (c:Component {{id: $id}})
        SET {set_clause}
        RETURN c {{.*}} as c
        """

        result = await self.db.run_single(query, **props)

        if not result or "c" not in result:
            raise UIError(f"Component {component_id} not found")

        updated = self._record_to_component(result["c"])
        logger.info(f"Component updated: id={component_id}")
        return updated

    async def update_component(
        self,
        component_id: str,
        name: str = "",
        uri: str = "",
        docs_url: str = "",
        description: str = "",
        **extra_fields: Any,
    ) -> Component:
        """Alias for update for manager compatibility."""
        return await self.update(
            component_id=component_id,
            name=name,
            uri=uri,
            docs_url=docs_url,
            description=description,
            **extra_fields,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Delete
    # ─────────────────────────────────────────────────────────────────────

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

    async def delete_component(self, component_id: str) -> None:
        """Alias for delete for manager compatibility."""
        await self.delete(component_id)

    # ─────────────────────────────────────────────────────────────────────
    # Dependencies
    # ─────────────────────────────────────────────────────────────────────

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

    async def check_component_dependencies(self, component_id: str) -> int:
        """Alias for count_dependencies for manager compatibility."""
        return await self.count_dependencies(component_id)