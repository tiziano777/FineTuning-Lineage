"""Relation types and relationship models for the lineage graph."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

class DerivedFrom(BaseModel):
    """Relationship payload for DERIVED_FROM edges between experiments.

    The diff_patch field contains a git-style diff structure:
    Type is ``dict[str, Any]`` for serialization flexibility.
    """

    source_exp_id: str = Field(..., min_length=1)
    target_exp_id: str = Field(..., min_length=1)
    diff_patch: dict[str, Any] = Field(default_factory=dict)
