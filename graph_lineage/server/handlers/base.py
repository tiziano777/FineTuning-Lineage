"""Abstract base class for run-type-specific lineage handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from graph_lineage.server.schemas import PreRequest, PostRequest


@dataclass(frozen=True)
class RunTypeResult:
    """Result of run-type detection."""

    strategy: str  # NEW | RETRY | BRANCH | RESUME | MERGE
    parent_run_id: str | None = None
    parent_ckp_id: str | None = None  # only for RESUME
    diff_patch: dict[str, str] | None = None  # only for BRANCH
    changed_files: list[str] | None = None  # filenames that differ (for description)
    extra: dict[str, Any] = field(default_factory=dict)  # escape-hatch for handler-specific data


class RunTypeHandler(ABC):
    """Un handler incapsula TUTTA la logica verticale di un run_type:
    detection strategia, creazione nodo + edge, e update a POST-time.
    """

    run_type: str

    @abstractmethod
    async def detect(self, request: PreRequest) -> RunTypeResult:
        """Detect the run strategy for this run type."""
        ...

    @abstractmethod
    def create_nodes(self, request: PreRequest, result: RunTypeResult) -> str:
        """Crea nodo (+ edge) nel grafo, ritorna il run_id creato."""
        ...

    def on_post(self, request: PostRequest) -> None:
        """Hook opzionale per side-effect a POST-time (default: no-op).
        Il caso RESUME/CKP_DERIVED_FROM del training va qui, non nell'endpoint.
        """
        return None