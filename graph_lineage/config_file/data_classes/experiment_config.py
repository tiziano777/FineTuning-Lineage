"""Strict experiment configuration — managed by the lineage hook."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExperimentConfig(BaseModel):
    """Strict experiment configuration — managed by the lineage hook."""

    id: str | None = None
    previous_experiment_id: str | None = None
    base_experiment_id: str | None = None
    base: bool | None
    name: str = Field(..., min_length=1)
    description: str = ""
    uri: str | None = None
    status: str | None = None
    checkpoint_resume_from: str | None = None
    model_id: str | None = None
    component_id: str | None = None
    recipe_id: str | None = None
