"""Marker tassonomico ACM: Case."""
from __future__ import annotations
from .base import BaseNode
from typing import List


class Case(BaseNode):
    """ACM Case -- Contenitore logico di un processo dinamico non strutturato (ACM Case)."""
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j."""
        labels = ["Case"]
        return labels