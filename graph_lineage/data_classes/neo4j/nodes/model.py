"""Pydantic models for Model entity."""

from __future__ import annotations
from typing import Optional
from pydantic import Field
from .base import BaseEntity

class Model(BaseEntity):
    """Model entity -- base model for fine-tuning."""

    model_name: str = Field(..., min_length=1, description="Unique model name")
    version: Optional[str] = Field("", description="Model version")
    uri: str = Field("", description="Path or URI to model")
    url: Optional[str] = Field("", description="Model URL (HuggingFace, etc)")
    doc_url: Optional[str] = Field("", description="Documentation URL")
    description: Optional[str] = Field("", description="Model description")
    kind: Optional[str] = Field("", description="Model kind: BASE | ADAPTER | MERGED")
    architecture_info_ref: Optional[str] = Field("", description="Reference to architecture document")
  
