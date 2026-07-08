"""Strict recipe configuration — snapshot for consistency guard."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Dict



class RecipeEntry(BaseModel):
    """Metadata for a single distribution/dataset entry in a recipe."""

    chat_type: str = Field(..., min_length=1, description="Chat conversation type")
    dist_id: str = Field(..., min_length=1, description="Distribution unique identifier")
    dist_name: str = Field(..., min_length=1, description="Human-readable distribution name")
    dist_uri: str = Field(..., min_length=1, description="Path or URI to distribution")
    replica: int = Field(1, ge=1, description="Replication factor (N× oversampling)")
    samples: int = Field(..., gt=0, description="Total number of samples in distribution")
    system_prompt: Optional[Dict[str, str]] = Field(None, description="System prompt name: content templates")
    tokens: int = Field(..., gt=0, description="Total token count")
    words: int = Field(..., gt=0, description="Total word count")
    validation_error: Optional[str] = Field(None, description="Validation error if any")


class RecipeConfig(BaseModel):
    """Strict recipe configuration — snapshot for consistency guard.

    Only 'entries' is required when a recipe is provided; all metadata
    fields are optional and non-blocking.
    """

    entries: dict[str, RecipeEntry] = Field(
        default_factory=dict,
        description="Mapping of dataset paths to distribution metadata",
    )
    id: str = Field(None, description="Recipe UUID")
    name: str = Field(..., description="Recipe short name")
    description: Optional[str] = Field(None, description="Human-readable description")
    scope: Optional[str] = Field(None, description="Training scope (e.g. continual_ft, sft)")
    tasks: Optional[list[str]] = Field(default_factory=list, description="Task categories covered")
    tags: Optional[list[str]] = Field(default_factory=list, description="Free-form classification tags")
    derived_from: Optional[str] = Field(None, description="Parent recipe UUID this was derived from")
