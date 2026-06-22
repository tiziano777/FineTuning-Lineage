"""Pydantic models for server API request/response schemas.

These mirror the client SDK models (modules/lineage/models.py) to keep
the API contract in sync.
"""

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

    codebase: str # JSON string of {relative_path: content}

    # BASE NODE RELATIONSHIPS
    model_id: str | None = None
    component_id: str | None = None
    recipe_id: str | None = None


    # Optional: checkpoint resume reference
    checkpoint_resume_from: str | None = None


class PreResponse(BaseModel):
    """Response sent back to client after PRE processing."""

    experiment_id: str
    strategy: str
    base: bool
    description: str
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None


# ─── POST-EXECUTION ───────────────────────────────────────────────────────────


class PostRequest(BaseModel):
    """Payload received from client after training ends."""

    experiment_id: str
    status: str
    exit_message: str | None = None
    metrics_uri: str | None = None


class PostResponse(BaseModel):
    """Acknowledgement sent back to client."""

    experiment_id: str
    status: str
    acknowledged: bool = True


# ─── HEALTH ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """Health check response."""

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
    """Acknowledgement sent back after checkpoint creation."""

    checkpoint_id: str
    experiment_id: str
    acknowledged: bool = True
