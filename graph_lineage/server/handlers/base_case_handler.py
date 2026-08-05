from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from graph_lineage.server.schemas import PostRequest, PreRequest

@dataclass(kw_only=True)
class CaseTypeResult:
    """Result of run-type detection.
        only extra field is defined, this is an abstract base class for all cases.
    """
    extra: dict[str, Any] = field(default_factory=dict)  # escape-hatch for handler-specific data

@dataclass()
class PreResolution:
    """Stato finale della fase PRE: cio' che app.py usa per costruire la PreResponse."""
    pass

@dataclass()
class PostResolution:
    """Stato finale della fase POST: cio' che app.py usa per costruire la PostResponse."""
    pass

class CaseHandler(ABC):

    @abstractmethod
    async def resolve_request(self, request: PreRequest) -> PreResolution:
        """Detect la strategy, applica l'update al grafo tramite il repository, e ritorna lo stato PRE finale."""
        ...

    @abstractmethod
    async def detect_strategy(self, request: PreRequest) -> CaseTypeResult:
        """Detect the case strategy for this run type. Nessuna scrittura sul grafo."""
        ...

    @abstractmethod
    def resolve_post(self, request: PostRequest) -> PostResolution:
        """Applica l'update POST-execution tramite il repository e ritorna lo stato finale."""
        ...
