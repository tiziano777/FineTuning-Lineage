# artifact.py
from __future__ import annotations
from typing import Optional
from pydantic import Field
from .source import Source

class Artifact(Source):
    """
    Artifact(Source) ACM class -- Entità immutabile prodotta da Case Execution (ACM Artifact(Source)).
    Marker tassonomico ACM: Artifact. Compatibile con ACM Source.
    
    Caso Base, Output finale di un Case o sotto-task, prodotto da un Event Handler al tempo T.
    Caso Custom: Entità prodotta dal sistema durante execution di unCase al tempo T.
     
    Eredita da `Source`, qualsiasi Artifact può essere direttamente utilizzato come Source
    in ingresso per un nuovo Case o sotto-task al tempo T+1.
    """

    # Opzionale: Tracciamento dell'evento Custom che lo ha generato nel Grafo.
    # Per gli artifact generati come output finale di un Case, questo campo è None.
    gen_event: Optional[str] = Field(
        default=None,
        description="Identificatore dell'Event Handler che ha generato questo Artifact",
    )