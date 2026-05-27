from __future__ import annotations

from pathlib import Path

import yaml

from .recipe_config import RecipeConfig, RecipeEntry


class RecipeLoader:
    """Parse a recipe YAML file or mapping into a validated RecipeConfig.

    Accepts either a path to a YAML file or an already-loaded mapping (dict).
    Also supports configuration files that embed the recipe under a top-level
    'recipe' key (e.g., config.yml).
    """

    @staticmethod
    def load(path: str | Path | dict) -> RecipeConfig:
        # Accept an already-parsed mapping
        if isinstance(path, dict):
            data = path
        else:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}

        # If the recipe is embedded under a top-level 'recipe' key, use it
        if isinstance(data, dict) and "recipe" in data and isinstance(data["recipe"], dict):
            data = data["recipe"]

        entries_mapping = data.get("entries", {}) or {}
        entries: dict[str, RecipeEntry] = {
            uri: RecipeEntry(**entry_data)
            for uri, entry_data in entries_mapping.items()
        }

        return RecipeConfig(
            recipe_id=data.get("id"),
            recipe_name=data.get("name"),
            description=data.get("description"),
            scope=data.get("scope"),
            tasks=data.get("tasks") or [],
            tags=data.get("tags") or [],
            derived_from=data.get("derived_from"),
            entries=entries,
        )
