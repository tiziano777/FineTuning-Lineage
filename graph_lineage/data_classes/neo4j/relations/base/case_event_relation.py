from typing import ClassVar, Type

from .base import BaseRelation
from ...nodes.base.case import Case
from ...nodes.base.event import Event


class CaseEventRelation(BaseRelation):
    """Relazione generica tra Case e Event."""
    source_type: ClassVar[Type] = Case
    target_type: ClassVar[Type] = Event