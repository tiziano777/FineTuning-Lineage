"""Pydantic models for Checkpoint entity."""

from __future__ import annotations
from pydantic import Field
from typing import Optional
from ..generic.run_event import RunEvent

class Checkpoint(RunEvent):
    """Checkpoint entity -- core tracking entity for a training run."""

    name: str = Field("", description="Checkpoint name")
    derived_from: str = Field("", description="Associated Model")

    epoch: Optional[int]
    run: Optional[int]
    uri: str = Field("", description="Path scaffold on worker")
    metrics: str = Field(default_factory=str, description="Training metrics")

    is_merging: bool = Field(True, description="Indicates if the checkpoint is merging")
    is_usable: bool = Field(True, description="Soft-delete flag for visibility")
