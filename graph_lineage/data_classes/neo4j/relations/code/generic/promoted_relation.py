# PromotedRelation — relazione generica tra RunEvent e RunResult
from __future__ import annotations
from typing import ClassVar, Type


from ...base.event_artifact_relation import EventArtifactRelation
from ....nodes.code.generic.run_result import RunResult
from ....nodes.code.generic.run_event import RunEvent


class PromotedRelation(EventArtifactRelation):
    source_type: ClassVar[Type] = RunEvent
    target_type: ClassVar[Type] = RunResult