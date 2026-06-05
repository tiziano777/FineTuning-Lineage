"""Merge configuration — required only when enabled=true."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelMergingConfig(BaseModel):
    """Merge configuration — required only when enabled=true."""

    enabled: bool = False
    lora_enabled: bool = False
    lora: dict[str, str] = {"base_model_path": "/path/to/base/model"}
    merge_method: str = "avg" 
    sources: list[str] = Field(default_factory=list)
