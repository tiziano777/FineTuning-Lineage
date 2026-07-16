from ..generic.promoted_relation import PromotedRelation
from typing import ClassVar, Type
from ....nodes.code.training.checkpoint import Checkpoint
from ....nodes.code.training.model import Model


class Promoted(PromotedRelation):
    source_type: ClassVar[Type] = Checkpoint
    target_type: ClassVar[Type] = Model
