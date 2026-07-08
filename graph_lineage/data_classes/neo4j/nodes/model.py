"""Pydantic models for Model entity."""

from __future__ import annotations
from typing import Optional
from pydantic import Field
from .base import BaseEntity
from enum import Enum

class ModelType(Enum):
    """Enum per i tipi di modelli LLM."""
    
    # Modelli base/fondazionali
    FOUNDATIONAL = "foundational"
    BASE = "base"
    
    # Modelli addestrati/istruiti
    INSTRUCT = "instruct"
    THINKING = "thinking"
    
    # Modelli specializzati
    DOMAIN_SPECIFIC = "domain_specific"
    FINE_TUNED = "fine_tuned"
    
    # Modelli derivati
    MERGED = "merged"
    DISTILLED = "distilled"
    
    # Modelli compressi
    QUANTIZED = "quantized"
    
    # Modelli multimodali
    MULTIMODAL = "multimodal"
    
    # Altri
    UNKNOWN = "unknown"

class Model(BaseEntity):
    """Model entity -- base model for fine-tuning."""

    model_name: str = Field(..., min_length=1, description="Unique model name")
    uri: str = Field("", description="Path or URI to model")
    version: Optional[str] = Field("", description="Model version")
    url: Optional[str] = Field("", description="Model URL (HuggingFace, etc)")
    doc_url: Optional[str] = Field("", description="Documentation URL")
    description: Optional[str] = Field("", description="Model description")
    
    kind: ModelType = Field(ModelType.UNKNOWN, description="Model Type (foundational, instruct, domain_specific, etc.)")
    architecture_info_ref: Optional[str] = Field("", description="Reference to architecture document")

  