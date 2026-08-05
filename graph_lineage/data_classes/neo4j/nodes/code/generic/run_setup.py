from ...base.source import Source
from typing import List

class Setup(Source):
    """Setup(Source) ACM class -- Entità immutabile, input di un Run(Case) (ACM Setup(Source))."""
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j."""
        labels = ["Source", "Setup"]
        return labels