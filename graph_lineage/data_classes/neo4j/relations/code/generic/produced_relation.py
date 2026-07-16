# PromotedRelation — relazione generica tra RunEvent e RunResult
from __future__ import annotations
from typing import ClassVar, Type


from ...base.case_artifact_relation import CaseArtifactRelation
from ....nodes.code.generic.run_result import RunResult
from ....nodes.code.generic.code_run import CodeRun


class ProducedRelation(CaseArtifactRelation):
    source_type: ClassVar[Type] = CodeRun
    target_type: ClassVar[Type] = RunResult