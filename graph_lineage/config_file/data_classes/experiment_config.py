"""Strict experiment configuration — managed by the lineage hook."""

from __future__ import annotations

from pydantic import BaseModel, Field
from graph_lineage.data_classes.neo4j.nodes.code.enum.run_type import RunType

# EXPERIMENT LINEAGE CONFIG FILE WRAPPER

class ExperimentConfig(BaseModel):
    """Strict experiment configuration — managed by the lineage hook."""

    id: str | None = None
    previous_experiment_id: str | None = None
    base_experiment_id: str | None = None
    base: bool | None
    name: str = Field(..., min_length=1)
    description: str = ""
    experiment_type: RunType = Field(..., description="training | evaluation | inference | merging")
    uri: str | None = None 
    status: str | None = None
    model: str | None = None 
    component: str | None = None
    recipe: str | None = None
