"""Pydantic models for Checkpoint entity."""

from __future__ import annotations
from typing import Optional
from pydantic import  Field
from .base import BaseEntity

class Checkpoint(BaseEntity):
    """Checkpoint entity -- core tracking entity for a training run."""

    name: str = Field("", description="Checkpoint name")
    derived_from: str = Field("", description="Associated Model")

    epoch: int
    run: int
    uri: str = Field("", description="Path scaffold on worker")
    metrics: dict = Field(default_factory=dict, description="Training metrics")

    is_merging: bool = Field(True, description="Indicates if the checkpoint is merging")
    is_usable: bool = Field(True, description="Soft-delete flag for visibility")
