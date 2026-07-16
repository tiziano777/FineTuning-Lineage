from typing import ClassVar, Type

from .base import BaseRelation
from ...nodes.base.event import Event
from ...nodes.base.artifact import Artifact


class EventArtifactRelation(BaseRelation):
    """Relazione generica tra Event e Artifact."""
    source_type: ClassVar[Type] = Event
    target_type: ClassVar[Type] = Artifact