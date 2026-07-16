# /graph_lineage/data_classes/neo4j/relations/code/generic/uses.py
from __future__ import annotations
from typing import ClassVar, Type

from ...base.case_source_relation import CaseSourceRelation
from ....nodes.code.generic.code_run import CodeRun
from ....nodes.code.generic.run_setup import Setup


# --- Astratta: Case usa una Source (ACM) --------------------------------
class UsesRelation(CaseSourceRelation):
    """Non pensata per essere istanziata direttamente: usare le sottoclassi tipizzate."""
    source_type: ClassVar[Type] = CodeRun
    target_type: ClassVar[Type] = Setup