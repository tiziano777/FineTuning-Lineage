"""Pydantic models for Recipe entity."""

from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from .base import BaseEntity
from typing import Optional

class RecipeEntry(BaseModel):
    """Metadata for a single distribution/dataset entry in a recipe."""

    chat_type: str = Field(..., min_length=1, description="Chat conversation type")
    dist_id: str = Field(..., min_length=1, description="Distribution unique identifier")
    dist_name: str = Field(..., min_length=1, description="Human-readable distribution name")
    dist_uri: str = Field(..., min_length=1, description="Path or URI to distribution")
    replica: int = Field(1, ge=1, description="Replication factor (N× oversampling)")
    samples: int = Field(..., gt=0, description="Total number of samples in distribution")
    system_prompt: list[str] | None = Field(None, description="System prompt templates")
    system_prompt_name: list[str] | None = Field(None, description="System prompt names")
    tokens: int = Field(..., gt=0, description="Total token count")
    words: int = Field(..., gt=0, description="Total word count")
    validation_error: str | None = Field(None, description="Validation error if any")

class Recipe(BaseEntity):
    """Configuration for recipe/distribution metadata.

    Maps dataset paths to their metadata entries with optional scope, tasks, tags, and derived_from.

    Note:
        name can be None at parse time (recipe from YAML without 'name' field).
        Use ensure_name(filename) to derive name from filename before persistence.
        Filename format: "my_recipe.yaml" → "my_recipe"
    """

    name: str = Field(None, min_length=1, description="Recipe name (must be unique)")
    description: Optional[str] = Field(None, description="Recipe description")
    scope: Optional[str] = Field(None, description="Scope for this recipe (e.g., 'sft', 'preference', 'rl')")
    tasks: list[str] = Field(default_factory=list, description="Tasks associated with this recipe")
    tags: list[str] = Field(default_factory=list, description="Tags for categorizing recipes")
    derived_from: Optional[str] = Field(None, description="Optional UUID of parent recipe this was derived from")
    entries: dict[str, RecipeEntry] = Field(
        ...,        
        description="Mapping of dataset paths to distribution metadata"
    )

    @model_validator(mode="after")
    def validate_recipe_name(self) -> Recipe:
        """Validate that name is not empty if provided and follows naming rules."""
        if self.name is not None and not self.name.strip():
            raise ValueError("Recipe name cannot be empty or whitespace")
        # Note: Uniqueness is enforced at DB layer (Neo4j constraint).
        # This validator ensures name is valid before DB checks.
        return self

    def ensure_name(self, filename: str) -> None:
        """Extract recipe name from filename and set if name is currently None.

        Extracts stem (filename without extension) from provided filename.
        Handles edge cases like "recipe.yaml.bak" → "recipe.yaml".

        Args:
            filename: Source filename (e.g., "my_recipe.yaml").

        Raises:
            ValueError: If extracted name is empty or whitespace-only.
        """
        if self.name is not None:
            # Already has a name, don't override
            return

        # Extract stem using pathlib, handling edge cases
        path = Path(filename)
        # Use rsplit to handle cases like "recipe.yaml.bak"
        name_with_extension = path.name
        if "." in name_with_extension:
            # Remove only the last extension
            extracted_name = name_with_extension.rsplit(".", 1)[0]
        else:
            extracted_name = name_with_extension

        # Validate extracted name
        if not extracted_name or not extracted_name.strip():
            raise ValueError(
                f"Recipe name required: provide 'name' field in YAML or upload file with valid filename"
            )

        self.name = extracted_name
