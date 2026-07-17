"""Pydantic models for CodeRun entity."""

from __future__ import annotations
from typing import Optional, List
from enum import Enum
from pydantic import Field, model_serializer, field_validator
import json
from ...base.case import Case
from typing import Dict, Any
from ...base.enum.status_type import StatusType
from ..enum.strategy_type import StrategyType
from ..enum.run_type import RunType


class CodeRun(Case):
    """CodeRun entity -- core tracking entity for a training run."""

    uri: str = Field(..., description="Path scaffold on worker")
    base: bool = Field(True, description="True for base experiment, False for derived")
    name: str = Field("", description="Experiment name, equal between experiments in the chain")
    chain_id: int = Field(0, ge=0, description="Chain ID for derived experiments in the chain (0 for base)")
    strategy: StrategyType = Field(..., description="NEW | BRANCH | RETRY")
    run_type: RunType = Field(..., description="type of execution, only general code exec for now")


    description: Optional[str] = Field("", description="Experiment description")
    status: StatusType = Field("RUNNING", description="RUNNING | COMPLETED | FAILED")
    exit_status: Optional[str] = None
    exit_msg: Optional[str] = None

    component_id: Optional[str] = Field(None, description="component_id used for entire lineage experimentations")

    codebase: Dict[str, Any] = Field(..., description="base=True: full snapshot dict[str, str]; base=False: unified diff dict")
    changed_files: list[str] = Field(default_factory=list, description="List of filenames that changed (for non-base experiments)")

    usable: bool = Field(True, description="Is experiment usable")
    manual_save: bool = Field(False, description="Manually saved")

    logs_uri: Optional[str] = Field( None, description="Pointer to unified training + HW metrics")

    agentic_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, 
        description="Contenitore libero per metadati generati dagli agenti o dalla UI"
    )

    # Validatori specifici per CodeRun
    @field_validator('run_type', mode='before')
    @classmethod
    def validate_run_type(cls, v):
        """Valida che run_type sia sempre CODE per CodeRun."""

        VALID_RUN_TYPE = {"code"}
        
        if isinstance(v, Enum):
            v_str = v.value
        else:
            v_str = v
        
        # CodeRun accetta solo CODE
        if v_str not in VALID_RUN_TYPE:
            raise ValueError(
                f"CodeRun can only have run_type='code', got '{v_str}'"
            )
        return v

    @field_validator('strategy', mode='before')
    @classmethod
    def validate_strategy(cls, v):
        """Valida che strategy sia valida per CodeRun."""
        valid_strategies = {"NEW", "BRANCH", "RETRY"}
        
        if isinstance(v, Enum):
            v_str = v.value
        else:
            v_str = v
        
        if v_str not in valid_strategies:
            raise ValueError(
                f"CodeRun strategy must be one of {valid_strategies}, got '{v_str}'"
            )
        return v

    # PROPRIETÀ DINAMICA PER LE ETICHETTE SU NEO4J
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j. Es: ['Run', 'Base']"""
        labels = ["Run"]
        if self.run_type:
            # Capitalizza per convenzione Neo4j
            labels.append(self.run_type.capitalize())
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
    
