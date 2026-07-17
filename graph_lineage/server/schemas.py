"""Pydantic models for Client-Server communication payloads."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from graph_lineage.data_classes.neo4j.nodes.code.enum.run_type import RunType

import json
import uuid

# ─── PRE-EXECUTION ─────────────────────────────────────────────────────────────

class PreRequest(BaseModel):
    """Payload sent to server before training execution starts.

    Contains the full experiment config and captured codebase content
    for the server to run rule detection and create the experiment node.
    """
    model_config = ConfigDict(populate_by_name=True)

    # Experiment identity
    experiment_id: Optional[str] = None
    experiment_name: str
    experiment_uri: Optional[str] = None
    base: Optional[bool] = None
    base_experiment_id: Optional[str] = None
    previous_experiment_id: Optional[str] = None
    description: Optional[str] = None
    run_type: RunType = Field(alias="experiment_type")
    merging: bool = False
    codebase: str  # JSON string of {relative_path: content}

    # BASE NODE RELATIONSHIPS
    model_id: Optional[str] = None
    model_uri: Optional[str] = None
    component_id: Optional[str] = None
    recipe_id: Optional[str] = None

class PreResponse(BaseModel):
    """Server response after PRE-execution processing.

    Contains the assigned experiment_id, detected strategy, and metadata
    the client needs to update local state.
    """

    experiment_id: str
    strategy: str  # NEW, RETRY, BRANCH, RESUME, MERGE
    base: bool
    description: str
    base_experiment_id: Optional[str] = None
    previous_experiment_id: Optional[str] = None

# ─── POST-EXECUTION ───────────────────────────────────────────────────────────

class PostRequest(BaseModel):
    """Payload sent to server after training execution ends.

    Reports final status and optional metrics URI.
    """

    experiment_id: str
    status: str  # COMPLETED or FAILED
    exit_message: Optional[str] = None
    metrics_uri: Optional[str] = None
    strategy: Optional[str] = None  # NEW, RETRY, BRANCH, RESUME, MERGE

class PostResponse(BaseModel):
    """Server acknowledgement of POST-execution update."""

    experiment_id: str
    status: str
    acknowledged: bool = True

# ─── HEALTH ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Server health check response."""

    status: str = "ok"
    version: str = ""
    neo4j_connected: bool = False

# ─── CHECKPOINT ────────────────────────────────────────────────────────────────

class CheckpointRequest(BaseModel):
    """Payload received from client when a checkpoint is saved."""

    experiment_id: str
    name: str
    epoch: int
    run: int
    uri: str
    metrics: str = Field(default_factory=str)
    derived_from: str = ""
    is_merging: bool = False


class CheckpointResponse(BaseModel):
    """Server acknowledgement of checkpoint creation."""

    checkpoint_id: str
    experiment_id: str
    acknowledged: bool = True

# ─── GENERIC NODE ─────────────────────────────────────────────────────────────

class EventNodeRequest(BaseModel):
    """Payload for creating a generic node linked to a run.

    REFACTOR: payload viene automaticamente serializzato in JSON string
    per evitare CypherTypeError (Neo4j non accetta Map come property value).
    """

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "run_id": "exp-123",
                "node_type": "Metric",
                "payload": {"name": "final_loss", "value": 0.123},
                "edge_type": "PRODUCED"
            }
        }
    )

    run_id: str
    node_type: str
    payload: dict[str, Any]
    edge_type: str = "PRODUCED"

    @model_validator(mode='after')
    def validate_payload_serializable(self):
        """Verifica che il payload sia serializzabile in JSON."""
        try:
            json.dumps(self.payload)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Payload must be JSON-serializable: {e}")
        return self

    def to_neo4j_params(self) -> dict[str, Any]:
        """Converte il modello in parametri primitivi per Neo4j.

        Returns:
            dict con payload serializzato in JSON string e tutti i valori
            come primitive (str, int, float, bool, None).
        """
        return {
            "node_id": str(uuid.uuid4()),
            "node_type": self.node_type,
            "payload_json": json.dumps(self.payload),  # Neo4j-safe: String
            "run_id": self.run_id,
            "edge_type": self.edge_type.upper(),
        }


class EventNodeResponse(BaseModel):
    """Server acknowledgement of generic node creation."""

    node_id: str
    acknowledged: bool = True
