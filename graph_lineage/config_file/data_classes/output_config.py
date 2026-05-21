"""Output paths configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OutputConfig(BaseModel):
    """Output paths configuration."""

    output_dir: str = Field(..., min_length=1)
    metrics_uri: str | None = None

