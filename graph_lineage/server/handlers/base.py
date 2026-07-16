"""Abstract base class for run-type-specific lineage handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from graph_lineage.core.state_provider import GitOrExplicitCodebaseProvider, StateProvider
from graph_lineage.data_classes.neo4j.nodes.code.training.experiment import StrategyType
from graph_lineage.diff.snapshot import CodebaseSnapshot
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

    La logica generica RETRY vs BRANCH (confronto hash di stato) è stata
    estratta in `detect_branch_or_retry()` e riutilizzabile da tutti i subclass.
    """

    run_type: str

    def __init__(self, state_provider: StateProvider | None = None):
        """Inizializza l'handler con uno StateProvider opzionale.

        Args:
            state_provider: Provider per snapshot/diff. Default: GitOrExplicitCodebaseProvider.
        """
        self.state_provider = state_provider or GitOrExplicitCodebaseProvider()

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

    # ── Logica condivisa estratta da TrainingRunHandler.detect() ─────────

    def detect_branch_or_retry(
        self,
        current_snapshot: CodebaseSnapshot,
        parent_snapshot: CodebaseSnapshot,
        parent_run_id: str,
    ) -> RunTypeResult:
        """Confronta due snapshot di stato e decide RETRY vs BRANCH.

        Questo metodo sostituisce i punti 3 e 4 duplicati in
        TrainingRunHandler.detect(), rendendo la logica riutilizzabile
        da qualsiasi handler di dominio futuro.

        Args:
            current_snapshot: Snapshot dello stato corrente (dal client).
            parent_snapshot: Snapshot dello stato parent (ricostruito dal DB).
            parent_run_id: ID del run parent per creare l'edge.

        Returns:
            RunTypeResult con strategy RETRY o BRANCH, diff_patch e changed_files.
        """
        identical, diff_patch = self.state_provider.compare(
            old_snapshot=parent_snapshot,
            new_snapshot=current_snapshot,
        )
        changed_files = sorted(diff_patch.keys()) if diff_patch else []

        if identical:
            return RunTypeResult(
                strategy=StrategyType.RETRY.value,
                parent_run_id=parent_run_id,
                diff_patch=diff_patch,
                changed_files=changed_files,
            )

        return RunTypeResult(
            strategy=StrategyType.BRANCH.value,
            parent_run_id=parent_run_id,
            diff_patch=diff_patch,
            changed_files=changed_files,
        )