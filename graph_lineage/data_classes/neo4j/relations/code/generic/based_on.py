from typing import ClassVar, Type

from ...base.artifact_source_relation import ArtifactSourceRelation
from ....nodes.code.generic.run_result import RunResult
from ....nodes.code.generic.run_setup import Setup


class FeedsRelation(ArtifactSourceRelation):
    source_type: ClassVar[Type] = RunResult
    target_type: ClassVar[Type] = Setup
