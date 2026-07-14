"""Pydantic models for Client-Server communication payloads."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from graph_lineage.data_classes.neo4j.nodes.experiment import RunType

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

    checkpoint_resume_from: Optional[str] = None

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
    strategy: Optional[str] = None  # NEW, RETRY, BRANCH, RESUME, MERGE or None
    checkpoint_resume_from: Optional[str] = None

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

class GenericNodeRequest(BaseModel):
    """Payload for creating a generic node linked to a run."""

    run_id: str
    node_type: str
    payload: dict[str, Any]
    edge_type: str = "produced"


class GenericNodeResponse(BaseModel):
    """Server acknowledgement of generic node creation."""

    node_id: str
    acknowledged: bool = True

