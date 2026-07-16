from typing import ClassVar, Type
from ..generic.emitted_relation import EmittedRelation
from ....nodes.code.training.checkpoint import Checkpoint
from ....nodes.code.training.experiment import Experiment


class Emitted(EmittedRelation):
    source_type: ClassVar[Type] = Experiment
    target_type: ClassVar[Type] = Checkpoint