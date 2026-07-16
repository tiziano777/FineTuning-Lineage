# RunRelation — relazione generica tra esperimenti
from __future__ import annotations
from typing import ClassVar, Type

from ...base.cases_relation import CasesRelation
from ....nodes.code.generic.code_run import CodeRun

class RunsRelation(CasesRelation):
    source_type: ClassVar[Type] = CodeRun
    target_type: ClassVar[Type] = CodeRun
   