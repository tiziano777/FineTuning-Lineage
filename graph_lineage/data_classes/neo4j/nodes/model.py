"""Pydantic models for Model entity."""

from __future__ import annotations
from typing import Optional
from pydantic import Field
from .base import BaseEntity
from enum import Enum

class KindEnum(str, Enum):
    """Enum for model kind."""
    NONE = "NONE"
    BASE = "BASE"
    ADAPTER = "ADAPTER"
    MERGED = "MERGED"

class Model(BaseEntity):
    """Model entity -- base model for fine-tuning."""

    model_name: str = Field(..., min_length=1, description="Unique model name")
    uri: str = Field("", description="Path or URI to model")
    version: Optional[str] = Field("", description="Model version")
    url: Optional[str] = Field("", description="Model URL (HuggingFace, etc)")
    doc_url: Optional[str] = Field("", description="Documentation URL")
    description: Optional[str] = Field("", description="Model description")
    
    kind: KindEnum = Field("NONE", description="Model kind: BASE | ADAPTER | MERGED")
    architecture_info_ref: Optional[str] = Field("", description="Reference to architecture document")
  