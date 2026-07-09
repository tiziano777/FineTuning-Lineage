"""Pydantic models for Experiment entity."""

from __future__ import annotations
from typing import Optional, List
from enum import Enum
from pydantic import Field, model_serializer, field_validator
import json
from .base import BaseEntity
from typing import Dict, Any

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
    uri: str = Field(..., description="Path scaffold on worker")
    base: bool = Field(True, description="True for base experiment, False for derived")
    name: str = Field("", description="Experiment name, equal between experiments in the chain")
    chain_id: int = Field(0, description="Chain ID for derived experiments in the chain (0 for base)")

    status: StatusType = Field("RUNNING", description="RUNNING | COMPLETED | FAILED")
    exit_status: Optional[str] = None
    exit_msg: Optional[str] = None
    strategy: StrategyType = Field(..., description="NEW | RESUME | BRANCH | RETRY")
    experiment_type: ExperimentType = Field("training", description="training | evaluation | inference | merging")

    model_id: Optional[str] = Field(None, description="model_id used for entire lineage experimentations")
    model_uri: Optional[str] = Field(None, description="model_uri used for entire lineage experimentations")
    recipe_id: Optional[str] = Field(None, description="recipe_id used for entire lineage experimentations")
    component_id: Optional[str] = Field(None, description="component_id used for entire lineage experimentations")

    codebase: Dict[str, Any] = Field(..., description="base=True: full snapshot dict[str, str]; base=False: unified diff dict")
    changed_files: list[str] = Field(default_factory=list, description="List of filenames that changed (for non-base experiments)")

    usable: bool = Field(True, description="Is experiment usable")
    manual_save: bool = Field(False, description="Manually saved")

    metrics_uri: Optional[str] = Field( None, description="Pointer to unified training + HW metrics")

    agentic_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, 
        description="Contenitore libero per metadati generati dagli agenti o dalla UI"
    )

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
    
    @field_validator('codebase', mode='before')
    @classmethod
    def deserialize_codebase(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {"raw_text": v} # Fallback se era testo semplice
        return v or {}

    @model_serializer(mode='wrap')
    def serialize_neo4j_compatible(self, handler):
        """Serializza automaticamente i campi complessi (Dict) in stringhe JSON per Neo4j."""
        # Ottiene il dizionario standard generato da Pydantic
        data = handler(self)
        
        # Converte il dizionario/mappa in stringa JSON se presente
        if "agentic_metadata" in data and isinstance(data["agentic_metadata"], dict):
            data["agentic_metadata"] = json.dumps(data["agentic_metadata"])
        
        if "codebase" in data and isinstance(data["codebase"], (dict, list)):
            data["codebase"] = json.dumps(data["codebase"])

        return data
    @field_validator('agentic_metadata', mode='before')
    @classmethod
    def deserialize_agentic_metadata(cls, v):
        if not v:  # Intercetta None, "" o stringhe vuote
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v