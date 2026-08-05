"""Marker tassonomico ACM: Source."""
from __future__ import annotations
from .base import BaseNode
from typing import List


class Source(BaseNode):
    """Source ACM class -- Risorsa immutabile in ingresso che alimenta un Case (ACM Source)."""
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j."""
        labels = ["Source"]
        return labels