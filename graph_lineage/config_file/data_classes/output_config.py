"""Output paths configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OutputConfig(BaseModel):
    """Output paths configuration."""

    output_dir: str | None = None
    metrics_uri: str | None = None
    plots_uri: str | None = None

