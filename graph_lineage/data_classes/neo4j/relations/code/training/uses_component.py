from __future__ import annotations
from typing import ClassVar, Type

from ..generic.uses_relation import UsesRelation
from ....nodes.code.training.experiment import Experiment
from ....nodes.code.training.component import Component


class UsesComponent(UsesRelation):
    source_type: ClassVar[Type] = Experiment
    target_type: ClassVar[Type] = Component