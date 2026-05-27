# recipe_config.py

from __future__ import annotations
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

class RecipeEntry(BaseModel):
    """Metadata for a single distribution/dataset entry in a recipe."""

    chat_type: str = Field(..., min_length=1, description="Chat conversation type")
    dist_id: str = Field(..., min_length=1, description="Distribution unique identifier")
    dist_name: str = Field(..., min_length=1, description="Human-readable distribution name")
    dist_uri: str = Field(..., min_length=1, description="Path or URI to distribution")
    replica: int = Field(1, ge=1, description="Replication factor (N× oversampling)")
    samples: int = Field(0, ge=0, description="Total number of samples in distribution")
    system_prompt: Optional[List[str]] = Field(None, description="System prompt templates")
    system_prompt_name: Optional[List[str]] = Field(None, description="System prompt names")
    tokens: int = Field(0, ge=0, description="Total token count")
    words: int = Field(0, ge=0, description="Total word count")
    validation_error: Optional[str] = Field(None, description="Validation error if any")


class RecipeConfig(BaseModel):
    """Full recipe configuration — preserves all metadata fields from the YAML.

    Only 'entries' is required; all other metadata fields are optional and non-blocking.
    The recipe will process successfully even if metadata is missing.
    """

    entries: Dict[str, RecipeEntry] = Field(
        ...,
        description="Mapping of dataset paths to distribution metadata (REQUIRED)"
    )
    recipe_id: Optional[str] = Field(None, description="Recipe UUID")
    recipe_name: Optional[str] = Field(None, description="Recipe short name")
    description: Optional[str] = Field(None, description="Human-readable description")
    scope: Optional[str] = Field(None, description="Training scope (e.g. continual_ft, sft)")
    tasks: List[str] = Field(default_factory=list, description="Task categories covered")
    tags: List[str] = Field(default_factory=list, description="Free-form classification tags")
    derived_from: Optional[str] = Field(None, description="Parent recipe UUID this was derived from")