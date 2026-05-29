"""Rich summary models for history navigation and rollback previews."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CheckpointSummary(BaseModel):
    """Content projection of Checkpoint for preview/navigation."""

    name: str = ""
    derived_from: str = ""
    epoch: int = 0
    run: int = 0
    uri: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    is_merging: bool = False
    is_usable: bool = True


class ExperimentSummary(BaseModel):
    """Compact view of an experiment for preview/navigation."""

    exp_id: str
    description: str = ""
    status: str = ""
    strategy: str = ""
    usable: bool = True
    config_hash: str = ""
    created_at: Optional[str] = None
    checkpoint_count: int = 0
    checkpoints: list[CheckpointSummary] = Field(default_factory=list)


class RollbackPreview(BaseModel):
    """What would be affected by a rollback -- rich info for human review."""

    target_exp_id: str
    affected_experiments: list[ExperimentSummary] = Field(default_factory=list)
    branch_count: int = 0
    total_experiments: int = 0
    total_checkpoints: int = 0
    warning: Optional[str] = None


class NavigationResult(BaseModel):
    """Result of a graph navigation operation."""

    exp_id: str
    summary: ExperimentSummary
    codebase: dict[str, str] = Field(default_factory=dict)
