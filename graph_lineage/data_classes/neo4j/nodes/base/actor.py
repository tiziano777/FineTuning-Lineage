"""Marker tassonomico ACM: Actor."""
from __future__ import annotations
from .base import BaseNode
from typing import List
from pydantic import Field
from .enum.role import Role


class Actor(BaseNode):
    """Actor ACM -- Entità che rappresenta un attore coinvolto in un Case (ACM Actor)."""
    name: str 
    role: Role = Field(default=Role.OWNER) 

    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j."""
        labels = ["Actor"]
        return labels