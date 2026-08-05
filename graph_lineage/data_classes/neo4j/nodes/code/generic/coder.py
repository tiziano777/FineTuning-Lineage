from ...base.actor import Actor
from typing import List

class Coder(Actor):
    """Coder(Actor) ACM class -- Entità che rappresenta un programmatore coinvolto come owner di un Run(Case) (ACM Coder(Actor))."""

    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j. Es: ['Run', 'Base']"""
        labels = ["Actor", "Coder"]
        return labels