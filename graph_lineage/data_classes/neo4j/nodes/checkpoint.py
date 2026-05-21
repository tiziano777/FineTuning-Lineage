"""Pydantic models for Checkpoint entity."""

from __future__ import annotations
from typing import Optional
from pydantic import  Field
from .base import BaseEntity

class Checkpoint(BaseEntity):
    """Checkpoint entity -- core tracking entity for a training run."""

    derived_from: str = Field("", description="Associated Model")
    description: Optional[str] = Field("", description="Checkpoint description")

    ckp_uri: str = Field("", description="Path scaffold on worker")
    final_metrics: dict = Field("", description="Pointer to training metrics")

    