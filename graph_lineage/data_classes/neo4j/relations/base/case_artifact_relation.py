from typing import ClassVar, Type

from .base import BaseRelation
from ...nodes.base.case import Case
from ...nodes.base.artifact import Artifact


class CaseArtifactRelation(BaseRelation):
    """Relazione generica tra Case e Artifact."""
    source_type: ClassVar[Type] = Case
    target_type: ClassVar[Type] = Artifact