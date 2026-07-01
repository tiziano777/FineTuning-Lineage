"""Pydantic models for Client-Server communication payloads."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ─── PRE-EXECUTION ─────────────────────────────────────────────────────────────

class PreRequest(BaseModel):
    """Payload sent to server before training execution starts.

    Contains the full experiment config and captured codebase content
    for the server to run rule_engine detection and create the experiment node.
    """

    # Experiment identity
    experiment_id: str | None = None  # assigned by server if not provided
    experiment_name: str
    experiment_uri: str | None = None
    base: bool | None 
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None
    description: str | None = None

    merging: bool = False

    codebase: str # JSON string of {relative_path: content}

    # BASE NODE RELATIONSHIPS
    model_id: str | None = None
    model_uri: str | None = None
    component_id: str | None = None
    recipe_id: str | None = None

    checkpoint_resume_from: str | None = None  # checkpoint_id to resume from, if any


class PreResponse(BaseModel):
    """Server response after PRE-execution processing.

    Contains the assigned experiment_id, detected strategy, and metadata
    the client needs to update local state.
    """

    experiment_id: str
    strategy: str  # NEW, RETRY, BRANCH, RESUME, MERGE
    base: bool
    description: str
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None

# ─── POST-EXECUTION ───────────────────────────────────────────────────────────

class PostRequest(BaseModel):
    """Payload sent to server after training execution ends.

    Reports final status and optional metrics URI.
    """

    experiment_id: str
    status: str  # COMPLETED or FAILED
    exit_message: str | None = None
    metrics_uri: str | None = None
    strategy: str | None = None  # NEW, RETRY, BRANCH, RESUME, MERGE or None
    checkpoint_resume_from: str | None = None  # checkpoint_uri to resume from, if any

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

