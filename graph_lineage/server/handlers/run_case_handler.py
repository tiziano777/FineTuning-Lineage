"""Abstract base class for run-type-specific lineage handlers."""

from abc import abstractmethod

from dataclasses import dataclass

from graph_lineage.case_state_provider.state_provider import GitOrExplicitCodebaseProvider, StateProvider
from graph_lineage.data_classes.neo4j.nodes.code.generic.enum.strategy_type import StrategyType
from graph_lineage.diff_util.snapshot import CodebaseSnapshot
from graph_lineage.server.schemas import PostRequest, PreRequest
from .base_case_handler import CaseHandler, CaseTypeResult
from graph_lineage.data_classes.neo4j.nodes.base.enum.status_type import StatusType
from .base_case_handler import PreResolution, PostResolution

@dataclass()
class PreRunResolution(PreResolution):
    """Stato finale della fase PRE: cio' che app.py usa per costruire la PreResponse."""
    run_id: str
    strategy: StrategyType
    base: bool
    description: str
    base_experiment_id: str | None = None

@dataclass()
class PostRunResolution(PostResolution):
    """Stato finale della fase POST: cio' che app.py usa per costruire la PostResponse."""
    experiment_id: str
    status: StatusType

@dataclass
class RunTypeResult(CaseTypeResult):
    """Result of run-type detection."""
    strategy: StrategyType  # NEW | RETRY | BRANCH | RESUME | MERGE
    parent_run_id: str | None = None
    parent_ckp_id: str | None = None  # only for RESUME
    diff_patch: dict[str, str] | None = None  # only for BRANCH
    changed_files: list[str] | None = None  # filenames that differ (for description)

class RunCaseHandler(CaseHandler):
    """Un handler incapsula TUTTA la logica verticale di un run_type:
    detection strategia (detect_strategy), applicazione della strategia
    tramite il proprio repository (resolve_request), e update a POST-time
    (resolve_post).

    La logica generica RETRY vs BRANCH (confronto hash di stato) è stata
    estratta in `detect_branch_or_retry()` e riutilizzabile da tutti i subclass.

    - detect_strategy: solo detection, nessuna scrittura sul grafo, ritorna RunTypeResult.
    - resolve_request: applica la strategy (scrittura sul grafo via repository) e ritorna PreRunResolution.
    - resolve_post: applica l'update POST-execution (via repository) e ritorna PostRunResolution.
    """

    run_type: str


    def __init__(self, state_provider: StateProvider | None = None):
        """Inizializza l'handler con uno StateProvider opzionale.

        Args:
            state_provider: Provider per snapshot/diff. Default: GitOrExplicitCodebaseProvider.
        """
        self.state_provider = state_provider or GitOrExplicitCodebaseProvider()

    @abstractmethod
    async def resolve_request(self, request: PreRequest) -> PreRunResolution:
        """Invoke detect_strategy(), applica la strategy tramite il repository, ritorna PreRunResolution."""
        ...

    @abstractmethod
    async def detect_strategy(self, request: PreRequest) -> RunTypeResult:
        """Detect the run strategy for this run type. Nessuna scrittura sul grafo."""
        ...

    @abstractmethod
    def resolve_post(self, request: PostRequest) -> PostRunResolution:
        """Applica l'update POST-execution tramite il repository e ritorna PostRunResolution."""
        ...


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
                strategy=StrategyType.RETRY,
                parent_run_id=parent_run_id,
                diff_patch=diff_patch,
                changed_files=changed_files,
            )

        return RunTypeResult(
            strategy=StrategyType.BRANCH,
            parent_run_id=parent_run_id,
            diff_patch=diff_patch,
            changed_files=changed_files,
        )
