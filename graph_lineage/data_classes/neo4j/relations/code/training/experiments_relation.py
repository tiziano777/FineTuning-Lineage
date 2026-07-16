# ExperimentRelation — relazione generica tra esperimenti
from __future__ import annotations
from typing import ClassVar, Type

from ..generic.runs_relation import RunsRelation
from ....nodes.code.training.experiment import Experiment

class ExperimentsRelation(RunsRelation):
    source_type: ClassVar[Type] = Experiment
    target_type: ClassVar[Type] = Experiment
    