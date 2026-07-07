"""Recipe-only validation without envelope dependencies."""

from __future__ import annotations

from typing import Optional

import yaml
from pydantic import ValidationError
import logging

from graph_lineage.data_classes.neo4j.nodes.recipe import Recipe

logger = logging.getLogger(__name__)


def validate_recipe_yaml(yaml_str: str) -> tuple[bool, Optional[Recipe], list[str]]:
    """Validate YAML recipe format (Recipe CRUD only, no envelope).

    Args:
        yaml_str: YAML content as string.

    Returns:
        Tuple of (is_valid, recipe_obj, error_list).
    """
    try:
        # Parse YAML
        data = yaml.safe_load(yaml_str)
        if data is None:
            raise ValueError("Empty YAML content")
        if not isinstance(data, dict):
            raise ValueError(f"Expected YAML dict, got {type(data).__name__}")

        # Se la ricetta è inserita sotto una chiave 'recipe' di un file config globale, srotolala
        if "recipe" in data and isinstance(data["recipe"], dict):
            data = data["recipe"]

        # CORREZIONE 1: Ora 'entries' deve essere una LISTA
        entries_data = data.get("entries")
        if entries_data is None or not isinstance(entries_data, list):
            raise ValueError("YAML must contain top-level 'entries' list of distribution metadata")

        # Extract recipe metadata (all optional at YAML load time)
        yaml_recipe_id = data.get("id")
        yaml_name = data.get("name")
        yaml_description = data.get("description")
        yaml_scope = data.get("scope")
        yaml_tasks = data.get("tasks") or data.get("tasks", [])  # Support plural/fallback
        yaml_tags = data.get("tags", [])
        yaml_derived_from = data.get("derived_from")

        # Create Recipe entity to validate entries structure
        # Note: Don't pass id if None — let BaseEntity default_factory generate UUID
        recipe_kwargs = {
            "name": yaml_name,
            "description": yaml_description,
            "scope": yaml_scope,
            "tasks": yaml_tasks,
            "tags": yaml_tags,
            "derived_from": yaml_derived_from,
            "entries": entries_data # CORREZIONE 2: Passa direttamente la lista validata
        }
        if yaml_recipe_id is not None:
            recipe_kwargs["id"] = yaml_recipe_id

        # Pydantic farà il parsing ciclando sulla lista di RecipeEntry
        recipe = Recipe(**recipe_kwargs)

        entries_count = len(recipe.entries)
        logger.info(
            "Recipe YAML validated: name=%s recipe_id=%s entries=%d scope=%s tasks=%s tags=%s",
            recipe.name, recipe.id, entries_count, yaml_scope, yaml_tasks, yaml_tags
        )
        return True, recipe, []

    except ValueError as e:
        logger.warning("Recipe validation failed: %s", str(e))
        return False, None, [f"Invalid YAML format: {str(e)}"]
    except ValidationError as e:
        errors = []
        for err in e.errors():
            field = ".".join(str(x) for x in err["loc"])
            msg = err["msg"]
            errors.append(f"{field}: {msg}")
        logger.warning("Recipe validation errors: %s", errors)
        return False, None, errors
    except Exception as e:
        logger.exception("Unexpected recipe validation error: %s", str(e))
        return False, None, [f"Validation error: {str(e)}"]
