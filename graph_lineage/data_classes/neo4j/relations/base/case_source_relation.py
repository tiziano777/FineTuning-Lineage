from typing import ClassVar, Type

from .base import BaseRelation
from ...nodes.base.case import Case
from ...nodes.base.source import Source


class CaseSourceRelation(BaseRelation):
    """Relazione generica tra Case e Source."""
    source_type: ClassVar[Type] = Case
    target_type: ClassVar[Type] = Source