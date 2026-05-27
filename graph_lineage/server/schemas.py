"""Pydantic models for server API request/response schemas.

These mirror the client SDK models (modules/lineage/models.py) to keep
the API contract in sync.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ─── PRE-EXECUTION ─────────────────────────────────────────────────────────────


class PreRequest(BaseModel):
    """Payload received from client before training starts."""

    experiment_name: str
    experiment_uri: str | None = None
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None
    description: str | None = None
    model_uri: str = ""
    model_id: str = ""
    codebase: dict[str, str] = Field(default_factory=dict)
    checkpoint_resume_from: str | None = None


class PreResponse(BaseModel):
    """Response sent back to client after PRE processing."""

    experiment_id: str
    strategy: str
    base: bool
    description: str
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None
    changed_files: list[str] = Field(default_factory=list)


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
