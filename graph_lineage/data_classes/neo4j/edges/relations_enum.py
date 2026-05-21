"""Relation types and relationship models for the lineage graph."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Relation Types ---

class RelationType(str, Enum):
    """All 8 relation types from the Neo4j lineage graph schema.

    Values are UPPER_CASE protocol constants (not lowercase config values).
    """

    USED_FOR = "USED_FOR"
    SELECTED_FOR = "SELECTED_FOR"
    BASED_ON = "BASED_ON"
    PRODUCED = "PRODUCED"
    DERIVED_FROM = "DERIVED_FROM"
    STARTED_FROM = "STARTED_FROM"
    RETRY_OF = "RETRY_OF"
    MERGED_FROM = "MERGED_FROM"
    PROMOTED_TO = "PROMOTED_TO"


class DerivedFrom(BaseModel):
    """Relationship payload for DERIVED_FROM edges between experiments.

    The diff_patch field contains a git-style diff structure:
    - keys ``config``, ``train``, ``requirements``, ``hyperparams`` map to ``list[dict]``
    - key ``rewards`` maps to ``dict[str, list[dict]]`` (per-file diffs)
    Type is ``dict[str, Any]`` for serialization flexibility.
    """

    source_exp_id: str = Field(..., min_length=1)
    target_exp_id: str = Field(..., min_length=1)
    diff_patch: dict[str, Any] = Field(default_factory=dict)
