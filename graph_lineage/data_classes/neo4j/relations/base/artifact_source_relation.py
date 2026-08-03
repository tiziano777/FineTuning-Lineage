# CaseRelation — relazione generica tra Cases
from __future__ import annotations
from typing import ClassVar, Type

from .base import BaseRelation
from ...nodes.base.artifact import Artifact
from ...nodes.base.source import Source


class ArtifactSourceRelation(BaseRelation):
    """Relazione generica tra Artifact e Artifact."""
    source_type: ClassVar[Type] = Artifact
    target_type: ClassVar[Type] = Source