# PromotedRelation — relazione generica tra RunEvent e RunResult
from __future__ import annotations
from typing import ClassVar, Type


from ...base.case_event_relation import CaseEventRelation
from ....nodes.code.generic.run_event import RunEvent
from ....nodes.code.generic.code_run import CodeRun


class EmittedRelation(CaseEventRelation):
    source_type: ClassVar[Type] = CodeRun
    target_type: ClassVar[Type] = RunEvent