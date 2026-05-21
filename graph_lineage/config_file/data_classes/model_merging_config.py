"""Merge configuration — required only when enabled=true."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelMergingConfig(BaseModel):
    """Merge configuration — required only when enabled=true."""

    enabled: bool = False
    merge_method: str | None = None
    sources: list[str] = Field(default_factory=list)
