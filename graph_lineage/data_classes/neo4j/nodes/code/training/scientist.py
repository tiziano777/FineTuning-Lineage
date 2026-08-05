from ..generic.coder import Coder
from typing import List

class Scientist(Coder):
    """Entità che rappresenta uno scienziato coinvolto come owner di un Experiment(Run(Case)) (ACM Experiment(Run(Case)))."""
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j."""
        labels = ["Actor", "Coder", "Scientist"]
        return labels