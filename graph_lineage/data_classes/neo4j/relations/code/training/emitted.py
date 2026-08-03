from typing import ClassVar, Type
from ..generic.produced_relation import ProducedRelation
from ....nodes.code.training.checkpoint import Checkpoint
from ....nodes.code.training.experiment import Experiment


class Emitted(ProducedRelation):
    source_type: ClassVar[Type] = Experiment
    target_type: ClassVar[Type] = Checkpoint