from ..generic.feeds import FeedsRelation
from typing import ClassVar, Type
from ....nodes.code.training.checkpoint import Checkpoint
from ....nodes.code.training.model import Model


class Promoted(FeedsRelation):
    source_type: ClassVar[Type] = Checkpoint
    target_type: ClassVar[Type] = Model
