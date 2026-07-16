# CaseRelation — relazione generica tra Cases
from __future__ import annotations
from typing import ClassVar, Type

from ..base.base import BaseRelation
from ...nodes.base.case import Case


class CasesRelation(BaseRelation):
    """Relazione generica tra Case e Source."""
    source_type: ClassVar[Type] = Case
    target_type: ClassVar[Type] = Case