"""Pydantic models for Experiment entity."""

from __future__ import annotations

from typing import Optional, List
from enum import Enum
from pydantic import Field
from .base import BaseEntity

class StatusType(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class StrategyType(str, Enum):
    NEW = "NEW"
    RESUME = "RESUME"
    BRANCH = "BRANCH"
    RETRY = "RETRY"

class ExperimentType(str, Enum):
    TRAINING = "training"
    EVALUATION = "evaluation"
    INFERENCE = "inference"
    MERGING = "merging"

class Experiment(BaseEntity):
    """Experiment entity -- core tracking entity for a training run."""

    description: Optional[str] = Field("", description="Experiment description")
    uri: str = Field("", description="Path scaffold on worker")
    base: bool = Field(True, description="True for base experiment, False for derived")
    name: str = Field("", description="Experiment name, equal between experiments in the chain")
    chain_id: int = Field(0, description="Chain ID for derived experiments in the chain (0 for base)")

    status: StatusType = Field("RUNNING", description="RUNNING | COMPLETED | FAILED")
    exit_status: Optional[str] = None
    exit_msg: Optional[str] = None
    strategy: StrategyType = Field("", description="NEW | RESUME | BRANCH | RETRY")
    experiment_type: ExperimentType = Field("training", description="training | evaluation | inference | merging")

    model_id: str | None = Field(None, description="model_id used for entire lineage experimentations")
    model_uri: str | None = Field(None, description="model_uri used for entire lineage experimentations")
    recipe_id: str | None = Field(None, description="recipe_id used for entire lineage experimentations")
    component_id: str | None = Field(None, description="component_id used for entire lineage experimentations")

    codebase: str = Field("", description="base=True: full snapshot dict[str, str]; base=False: unified diff dict")
    changed_files: list[str] = Field(default_factory=list, description="List of filenames that changed (for non-base experiments)")

    usable: bool = Field(True, description="Is experiment usable")
    manual_save: bool = Field(False, description="Manually saved")

    metrics_uri: str | None = Field( None, description="Pointer to unified training + HW metrics")

    # PROPRIETÀ DINAMICA PER LE ETICHETTE SU NEO4J
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j. Es: ['Experiment', 'Training']"""
        labels = ["Experiment"]
        if self.experiment_type:
            # Capitalizza per convenzione Neo4j (training -> Training)
            labels.append(self.experiment_type.capitalize())
        if self.base:
            labels.append("Base")
        
        return labels
