from ...base.artifact import Artifact
from typing import List

class RunResult(Artifact):
    """RunResult(Artifact) ACM class -- Entità immutabile prodotta da un Run(Case) (ACM RunResult Artifact)."""
    @property
    def __labels__(self) ->  List[str]:
        """Genera le etichette per Neo4j."""
        labels = ["Artifact", "RunResult"]
        return labels