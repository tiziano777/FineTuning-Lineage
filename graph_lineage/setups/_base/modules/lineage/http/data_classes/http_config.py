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
    experiment_name: str
    experiment_uri: str | None = None
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None
    description: str | None = None

    # Model info
    model_uri: str = ""
    model_id: str = ""

    # Codebase content (full file contents, relative paths as keys)
    codebase: dict[str, str] = Field(default_factory=dict)

    # Optional: checkpoint resume reference
    checkpoint_resume_from: str | None = None

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
    changed_files: list[str] = Field(default_factory=list)

# ─── POST-EXECUTION ───────────────────────────────────────────────────────────

class PostRequest(BaseModel):
    """Payload sent to server after training execution ends.

    Reports final status and optional metrics URI.
    """

    experiment_id: str
    status: str  # COMPLETED or FAILED
    exit_message: str | None = None
    metrics_uri: str | None = None

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
    """Payload sent to server when a checkpoint is saved during training."""

    experiment_id: str
    name: str
    epoch: int
    run: int
    uri: str
    metrics: dict = Field(default_factory=dict)
    derived_from: str = ""
    is_merging: bool = False

class CheckpointResponse(BaseModel):
    """Server acknowledgement of checkpoint creation."""

    checkpoint_id: str
    experiment_id: str
    acknowledged: bool = True

