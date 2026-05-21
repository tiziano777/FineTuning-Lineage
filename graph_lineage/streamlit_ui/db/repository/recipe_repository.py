"""Repository for Recipe entity - Neo4j data access layer."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

import yaml
from pydantic import ValidationError

from graph_lineage.data_classes.neo4j.nodes.recipe import Recipe
from graph_lineage.streamlit_ui.utils.errors import UIError, DuplicateRecipeError
from graph_lineage.streamlit_ui.utils.entity_constraints import EntityConstraints
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class RecipeRepository:
    """Data access layer for Recipe entity."""

    def __init__(self, db_client: AsyncNeo4jClient):
        """Initialize repository with Neo4j client.

        Args:
            db_client: AsyncNeo4jClient for database queries.
        """
        self.db = db_client
        self.constraints = EntityConstraints(db_client)

    async def get_by_name(self, name: str) -> Optional[dict]:
        """Retrieve recipe by name.

        Args:
            name: Recipe name to lookup.

        Returns:
            Recipe data if found, None otherwise.

        Raises:
            UIError: On database query failure.
        """
        logger.debug(f"Querying recipe by name: {name}")
        try:
            query = """
            MATCH (r:Recipe {name: $name})
            RETURN r.id as id, r.name as name, r.description as description,
                   r.scope as scope, r.tasks as tasks, r.tags as tags, r.derived_from as derived_from,
                   r.entries as entries, r.created_at as created_at, r.updated_at as updated_at
            """
            result = await self.db.query(query, {"name": name})
            if result:
                row = result[0]
                entries_val = row.get('entries')
                if isinstance(entries_val, str):
                    try:
                        row['entries'] = json.loads(entries_val)
                    except Exception:
                        logger.exception("Failed to parse entries JSON for recipe %s", name)
                entry_count = len(row.get('entries', {})) if row.get('entries') else 0
                logger.debug(f"Recipe found: {name} (entry_count={entry_count})")
                if 'id' not in row and row.get('name'):
                    row['id'] = row.get('name')
                return row
            logger.debug(f"Recipe not found: {name}")
            return None
        except Exception as e:
            logger.error(f"Failed to get recipe by name: {e}")
            raise UIError(f"Failed to retrieve recipe: {str(e)}")

    async def get_by_id(self, id: str) -> Optional[dict]:
        """Retrieve recipe by ID."""
        logger.debug(f"Querying recipe by ID: {id}")
        try:
            query = """
            MATCH (r:Recipe {id: $id})
            RETURN r.id as id, r.name as name, r.description as description,
                   r.scope as scope, r.tasks as tasks, r.tags as tags, r.derived_from as derived_from,
                   r.entries as entries, r.created_at as created_at, r.updated_at as updated_at
            """
            result = await self.db.query(query, {"id": id})
            if result:
                row = result[0]
                entries_val = row.get('entries')
                if isinstance(entries_val, str):
                    try:
                        row['entries'] = json.loads(entries_val)
                    except Exception:
                        logger.exception("Failed to parse entries JSON for recipe_id %s", id)
                return row
            return None
        except Exception as e:
            logger.error(f"Failed to get recipe by recipe_id: {e}")
            raise UIError(f"Failed to retrieve recipe: {str(e)}")

    async def create_from_yaml(
        self,
        yaml_content: str,
        description: str = "",
    ) -> dict:
        """Create recipe from YAML content with full metadata extraction.

        Parses YAML, validates entries, and creates recipe with all metadata
        (scope, tasks, tags, derived_from).

        Args:
            yaml_content: YAML content string containing entries and metadata.
            description: Optional description (overrides YAML description if provided).

        Returns:
            Created recipe data.

        Raises:
            UIError: If YAML parsing or creation fails.
            DuplicateRecipeError: If recipe name or ID already exists.
        """
        try:
            logger.debug("Recipe upload: yaml_size=%d bytes", len(yaml_content))
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                raise UIError("YAML must contain a dictionary")

            # Extract entries (required)
            entries_data = data.get("entries")
            if entries_data is None or not isinstance(entries_data, dict):
                raise UIError("YAML must contain top-level 'entries' mapping of dataset URIs to metadata")

            # Extract metadata (all optional at YAML load time)
            yaml_name = data.get("name")
            yaml_description = data.get("description") if "description" in data else None
            yaml_id = data.get("id")
            yaml_scope = data.get("scope")
            yaml_tasks = data.get("task") or data.get("tasks", [])  # Support both singular/plural
            yaml_tags = data.get("tags", [])
            yaml_derived_from = data.get("derived_from")

            logger.debug(f"[DEBUG] Parsed YAML: name={yaml_name} id={yaml_id} entries={len(entries_data)}")

            # Create Recipe to validate entries structure
            # Only pass id if provided in YAML; otherwise let default_factory generate it
            recipe_kwargs = {
                "name": yaml_name,
                "entries": entries_data,
                "description": yaml_description,
                "scope": yaml_scope,
                "tasks": yaml_tasks,
                "tags": yaml_tags,
                "derived_from": yaml_derived_from
            }
            if yaml_id is not None:
                recipe_kwargs["id"] = yaml_id

            config = Recipe(**recipe_kwargs)
            logger.info(f"Recipe YAML parsed: name={config.name} entries={len(config.entries)}")

            # Convert entries to plain dicts
            entries_dict = {
                path: entry.model_dump(mode="json", exclude_none=True)
                for path, entry in config.entries.items()
            }

            # Determine recipe_id: use provided or generate new UUID
            if yaml_id:
                recipe_id = str(yaml_id)
            else:
                recipe_id = str(uuid.uuid4())

            final_description = description if description and description.strip() else yaml_description

            logger.info("Creating recipe from YAML: recipe_id=%s name=%s entry_count=%d", recipe_id, config.name, len(entries_dict))

            # Delegate to create() for database insertion
            result = await self.create(
                id=recipe_id,
                name=config.name,
                entries=entries_dict,
                description=final_description,
                scope=yaml_scope or "",
                tasks=yaml_tasks or [],
                tags=yaml_tags or [],
                derived_from=yaml_derived_from,
            )

            logger.info("Recipe created from YAML: recipe_id=%s name=%s entry_count=%d", recipe_id, result.get("name"), len(entries_dict))
            return result

        except (UIError, DuplicateRecipeError, ValidationError) as e:
            raise
        except Exception as e:
            logger.error(f"Recipe YAML creation failed: {str(e)}", exc_info=True)
            raise UIError(f"Failed to create recipe: {str(e)}")

    async def upsert_by_uri(
        self,
        uri: str,
        name: str,
        description: str = "",
        scope: str = "",
        tasks: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Upsert recipe by URI using MERGE semantics.

        Creates the recipe if no recipe with this URI exists,
        otherwise updates all fields on the existing recipe.

        Args:
            uri: Unique recipe URI (merge key).
            name: Recipe name.
            description: Recipe description.
            scope: Recipe scope.
            tasks: List of tasks.
            tags: List of tags.

        Returns:
            Upserted recipe data.
        """
        now = datetime.utcnow().isoformat()
        recipe_id = str(uuid.uuid4())
        query = """
        MERGE (r:Recipe {uri: $uri})
        ON CREATE SET r.id = $id, r.name = $name, r.description = $description,
                      r.scope = $scope, r.tasks = $tasks, r.tags = $tags,
                      r.created_at = $created_at, r.updated_at = $updated_at
        ON MATCH SET r.name = $name, r.description = $description,
                     r.scope = $scope, r.tasks = $tasks, r.tags = $tags,
                     r.updated_at = $updated_at
        RETURN r.id as id, r.name as name, r.uri as uri, r.description as description,
               r.scope as scope, r.tasks as tasks, r.tags as tags,
               r.created_at as created_at, r.updated_at as updated_at
        """
        result = await self.db.query(query, {
            "id": recipe_id,
            "uri": uri,
            "name": name,
            "description": description,
            "scope": scope,
            "tasks": tasks or [],
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
        })
        if not result:
            raise UIError("Failed to upsert recipe")
        logger.info(f"Recipe upserted: uri={uri}, name={name}")
        return dict(result[0])

    async def create(
        self,
        id: str,
        name: str,
        entries: dict,
        description: str = "",
        scope: str = "",
        tasks: list[str] | None = None,
        tags: list[str] | None = None,
        derived_from: str | None = None,
    ) -> dict:
        """Create a new recipe.

        Args:
            id: Unique recipe ID.
            name: Unique recipe name.
            entries: Dictionary mapping paths to RecipeEntry data.
            description: Optional recipe description.
            scope: Optional scope (e.g., 'sft', 'preference', 'rl').
            tasks: Optional list of tasks.
            tags: Optional list of tags.
            derived_from: Optional UUID of parent recipe this was derived from.

        Returns:
            Created recipe data.

        Raises:
            DuplicateRecipeError: If name already exists.
            UIError: If database query fails.
        """
        # Check uniqueness by recipe_id first
        logger.debug("Checking recipe uniqueness: id=%s name=%s", id, name)
        existing_by_id = await self.get_by_id(id)
        if existing_by_id:
            logger.warning("Recipe id already exists: %s", id)
            raise DuplicateRecipeError(id, recovery_suggestions=[f"{id}_dup"])

        # If name provided, ensure name is unique
        if name:
            existing_by_name = await self.get_by_name(name)
            if existing_by_name and existing_by_name.get('id') != id:
                logger.warning("Recipe name already exists: %s", name)
                suggestions = [f"{name}_v1", f"{name}_v2", f"{name}_backup"]
                raise DuplicateRecipeError(name, recovery_suggestions=suggestions)

        try:
            entry_count = len(entries)
            logger.info(f"Inserting recipe: name={name}, entry_count={entry_count}")
            query = """
            CREATE (r:Recipe {
                id: $id,
                name: $name,
                description: $description,
                scope: $scope,
                tasks: $tasks,
                tags: $tags,
                derived_from: $derived_from,
                entries: $entries,
                created_at: datetime(),
                updated_at: datetime()
            })
            RETURN r.id as id, r.name as name, r.description as description,
                   r.scope as scope, r.tasks as tasks, r.tags as tags, r.derived_from as derived_from,
                   r.entries as entries, r.updated_at as updated_at
            """
            # Serialize entries to JSON string
            try:
                entries_payload = json.dumps(entries)
            except Exception:
                logger.exception("Failed to serialize entries for recipe %s", name)
                raise UIError("Failed to serialize recipe entries for storage")

            result = await self.db.query(query, {
                "id": id,
                "name": name,
                "description": description,
                "scope": scope,
                "tasks": tasks or [],
                "tags": tags or [],
                "derived_from": derived_from,
                "entries": entries_payload,
            })
            if result:
                row = result[0]
                if isinstance(row.get('entries'), str):
                    try:
                        row['entries'] = json.loads(row['entries'])
                    except Exception:
                        logger.exception("Failed to parse returned entries JSON for recipe %s", name)
                logger.info(f"Recipe inserted successfully: name={row['name']}")
                return row
            raise UIError("Failed to create recipe")
        except Exception as e:
            if isinstance(e, (UIError, DuplicateRecipeError)):
                raise
            logger.error(f"Recipe insertion failed: {name}", exc_info=True)
            raise UIError(f"Failed to create recipe: {str(e)}")

    async def update(
        self,
        recipe_id: str,
        new_name: Optional[str] = None,
        description: Optional[str] = None,
        scope: Optional[str] = None,
        tasks: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """Update recipe metadata.

        Args:
            recipe_id: Recipe ID to update.
            new_name: New name (must be unique if provided).
            description: New description.
            scope: New scope.
            tasks: New tasks list.
            tags: New tags list.

        Returns:
            Updated recipe data.

        Raises:
            UIError: If recipe not found or conflict occurs.
        """
        existing = await self.get_by_id(recipe_id)
        if not existing:
            raise UIError(f"Recipe not found")

        # Check new name uniqueness if changing
        if new_name and new_name != existing.get('name'):
            conflict = await self.get_by_name(new_name)
            if conflict and conflict.get('id') != recipe_id:
                raise UIError(f"Recipe '{new_name}' already exists")

        try:
            updates: dict = {}
            if new_name:
                updates["name"] = new_name
            if description is not None:
                updates["description"] = description
            if scope is not None:
                updates["scope"] = scope
            if tasks is not None:
                updates["tasks"] = tasks
            if tags is not None:
                updates["tags"] = tags

            if not updates:
                return existing

            logger.info(f"Updating recipe: recipe_id={recipe_id}, fields={list(updates.keys())}")
            set_clause = ", ".join([f"r.{k} = ${k}" for k in updates.keys()])
            query = f"""
            MATCH (r:Recipe {{id: $id}})
            SET {set_clause}
            RETURN r.id as id, r.name as name, r.description as description,
                   r.scope as scope, r.tasks as tasks, r.tags as tags, r.derived_from as derived_from, r.entries as entries
            """
            params = {"id": recipe_id, **updates}
            result = await self.db.query(query, params)
            if result:
                row = result[0]
                if isinstance(row.get('entries'), str):
                    try:
                        row['entries'] = json.loads(row['entries'])
                    except Exception:
                        logger.exception("Failed to parse entries JSON on update")
                logger.info(f"Recipe updated: {row.get('id')}")
                return row
            raise UIError("Failed to update recipe")
        except Exception as e:
            if isinstance(e, UIError):
                raise
            logger.error(f"Recipe update failed: {recipe_id}", exc_info=True)
            raise UIError(f"Failed to update recipe: {str(e)}")

    async def is_deletable(self, recipe_id: str) -> bool:
        """Check if recipe can be deleted (no related experiments).

        Args:
            recipe_id: Recipe ID to check.

        Returns:
            True if recipe has no related experiments, False otherwise.
        """
        existing = await self.get_by_id(recipe_id)
        if not existing:
            return True  # Doesn't exist, considered deletable
        recipe_name = existing.get("name")
        if recipe_name:
            return await self.constraints.is_recipe_deletable(recipe_name)
        return True

    async def delete(self, recipe_id: str) -> None:
        """Delete recipe by recipe_id.

        Args:
            recipe_id: Recipe ID to delete.

        Raises:
            UIError: If recipe not found, has related experiments, or query fails.
        """
        existing = await self.get_by_id(recipe_id)
        if not existing:
            raise UIError(f"Recipe '{recipe_id}' not found")

        # Check if recipe can be deleted (no related experiments)
        if not await self.is_deletable(recipe_id):
            recipe_name = existing.get("name", recipe_id)
            raise UIError(
                f"Cannot delete recipe '{recipe_name}': it's used by one or more experiments. "
                "Remove experiments first before deleting the recipe."
            )

        try:
            logger.info("Deleting recipe: recipe_id=%s", recipe_id)
            query = "MATCH (r:Recipe {id: $id}) DELETE r"
            await self.db.query(query, {"id": recipe_id})
            logger.info("Recipe deleted: recipe_id=%s", recipe_id)
        except Exception as e:
            logger.error(f"Recipe deletion failed: {recipe_id}", exc_info=True)
            raise UIError(f"Failed to delete recipe: {str(e)}")

    async def list_all(self) -> list[dict]:
        """List all recipes.

        Returns:
            List of recipe data.

        Raises:
            UIError: On database query failure.
        """
        try:
            logger.debug("Listing all recipes")
            query = """
            MATCH (r:Recipe)
            RETURN r.id as id, r.name as name, r.description as description, r.scope as scope,
                   r.tasks as tasks, r.tags as tags, r.derived_from as derived_from,
                   r.created_at as created_at, r.updated_at as updated_at, r.entries as entries
            ORDER BY r.created_at DESC
            """
            result = await self.db.query(query)
            rows = result or []
            for row in rows:
                if isinstance(row.get('entries'), str):
                    try:
                        row['entries'] = json.loads(row['entries'])
                    except Exception:
                        logger.exception("Failed to parse entries JSON in list_all")
            logger.debug(f"Found {len(rows)} recipes")
            return rows
        except Exception as e:
            logger.error(f"Failed to list recipes: {e}")
            raise UIError(f"Failed to list recipes: {str(e)}")

    async def list_with_limit(self, limit: int = 20) -> list[dict]:
        """List recipes with limit.

        Args:
            limit: Maximum recipes to return.

        Returns:
            List of recipe data.

        Raises:
            UIError: On database query failure.
        """
        try:
            logger.debug(f"Listing recipes (limit={limit})")
            query = """
            MATCH (r:Recipe)
            RETURN r.id as id, r.name as name, r.description as description, r.scope as scope,
                   r.tasks as tasks, r.tags as tags, r.derived_from as derived_from,
                   r.created_at as created_at, r.updated_at as updated_at, r.entries as entries
            ORDER BY r.created_at DESC
            LIMIT $limit
            """
            result = await self.db.query(query, {"limit": limit})
            rows = result or []
            for row in rows:
                if isinstance(row.get('entries'), str):
                    try:
                        row['entries'] = json.loads(row['entries'])
                    except Exception:
                        logger.exception("Failed to parse entries JSON in list_with_limit")
            logger.debug(f"Found {len(rows) if rows else 0} recipes")
            return rows
        except Exception as e:
            logger.error(f"Failed to list recipes: {e}")
            raise UIError(f"Failed to list recipes: {str(e)}")

    async def search(self, query_str: str) -> list[dict]:
        """Search recipes by name.

        Args:
            query_str: Search query string.

        Returns:
            List of matching recipes.

        Raises:
            UIError: On database query failure.
        """
        try:
            logger.debug(f"Searching recipes: query={query_str}")
            cypher_query = """
            MATCH (r:Recipe)
            WHERE toLower(r.name) CONTAINS toLower($query)
            RETURN r.id as id, r.name as name, r.description as description, r.scope as scope,
                   r.tasks as tasks, r.tags as tags, r.derived_from as derived_from,
                   r.created_at as created_at, r.updated_at as updated_at, r.entries as entries
            ORDER BY r.created_at DESC
            """
            result = await self.db.query(cypher_query, {"query": query_str})
            rows = result or []
            for row in rows:
                if isinstance(row.get('entries'), str):
                    try:
                        row['entries'] = json.loads(row['entries'])
                    except Exception:
                        logger.exception("Failed to parse entries JSON in search")
            logger.debug(f"Found {len(rows) if rows else 0} recipes matching '{query_str}'")
            return rows
        except Exception as e:
            logger.error(f"Failed to search recipes: {e}")
            raise UIError(f"Failed to search recipes: {str(e)}")
