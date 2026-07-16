"""Pydantic models for Experiment entity."""

from __future__ import annotations
from typing import Optional, List
from enum import Enum
from pydantic import Field, field_validator
from ..generic.code_run import CodeRun

class Experiment(CodeRun):
    """Experiment entity -- core tracking entity for a training run."""

    model_id: Optional[str] = Field(None, description="model_id used for entire lineage experimentations")
    model_uri: Optional[str] = Field(None, description="model_uri used for entire lineage experimentations")

    # Validatori specifici per Experiment
    @field_validator('run_type', mode='before')
    @classmethod
    def validate_run_type_experiment(cls, v):
        """Valida run_type specifico per Experiment."""
        valid_types = {"training", "evaluation", "inference", "merging"}
        
        if isinstance(v, Enum):
            v_str = v.value
        else:
            v_str = v
        
        if v_str not in valid_types:
            raise ValueError(
                f"Experiment run_type must be one of {valid_types}, got '{v_str}'"
            )
        return v

    @field_validator('strategy', mode='before')
    @classmethod
    def validate_strategy_experiment(cls, v):
        """Valida strategy specifica per Experiment."""
        valid_strategies = {"NEW", "RESUME", "BRANCH", "RETRY"}
        
        if isinstance(v, Enum):
            v_str = v.value
        else:
            v_str = v
        
        if v_str not in valid_strategies:
            raise ValueError(
                f"Experiment strategy must be one of {valid_strategies}, got '{v_str}'"
            )
        return v

    # PROPRIETÀ DINAMICA PER LE ETICHETTE SU NEO4J
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j. Es: ['Experiment', 'Training']"""
        labels = ["Experiment"]
        if self.run_type:
            # Capitalizza per convenzione Neo4j (training -> Training)
            labels.append(self.run_type.capitalize())
        if self.base:
            labels.append("Base")
        
        return labels
