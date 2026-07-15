"""StateProvider: domain-agnostic snapshot and diff abstraction.

Estrae la logica di confronto codebase da TrainingRunHandler,
rendendola riutilizzabile da qualsiasi dominio futuro.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from graph_lineage.diff.differ import compute_snapshot_diff
from graph_lineage.diff.snapshot import CodebaseSnapshot


@dataclass
class StateProvider(ABC):
    """Fornisce snapshot di stato e confronto diff con pattern di ignore configurabili.

    Ogni implementazione definisce come catturare lo stato (git, filesystem, DB, etc.)
    e quali pattern ignorare nel confronto.
    """

    ignore_patterns: list[str] = field(default_factory=lambda: [
        ".lineage/experiment.yml",
        ".lineage/server.yml",
    ])

    def filtered_hashes(self, snapshot: CodebaseSnapshot) -> dict[str, str]:
        """Ritorna gli hash dello snapshot escludendo i pattern configurati.

        Sostituisce i 4 `pop(".lineage/experiment.yml", None)` hardcoded
        in TrainingRunHandler.detect().
        """
        hashes = snapshot.hashes()
        return {
            path: h
            for path, h in hashes.items()
            if not any(fnmatch(path, pattern) for pattern in self.ignore_patterns)
        }

    def diff(self, old_snapshot: CodebaseSnapshot, new_snapshot: CodebaseSnapshot) -> dict[str, Any]:
        """Calcola il diff tra due snapshot usando la logica condivisa."""
        return compute_snapshot_diff(old_snapshot=old_snapshot, new_snapshot=new_snapshot)

    def compare(self, old_snapshot: CodebaseSnapshot, new_snapshot: CodebaseSnapshot) -> tuple[bool, dict[str, Any]]:
        """Confronta due snapshot e ritorna (identical, diff_patch).

        Returns:
            identical: True se gli hash filtrati sono identici (→ RETRY)
            diff_patch: Il patch completo per BRANCH / descrizione
        """
        old_hashes = self.filtered_hashes(old_snapshot)
        new_hashes = self.filtered_hashes(new_snapshot)
        diff_patch = self.diff(old_snapshot, new_snapshot)
        return old_hashes == new_hashes, diff_patch

    @abstractmethod
    def snapshot(self) -> CodebaseSnapshot:
        """Cattura lo stato corrente e ritorna un CodebaseSnapshot."""
        ...


class GitOrExplicitCodebaseProvider(StateProvider):
    """Implementazione attuale: usa i file espliciti passati dal client.

    Il client (LineageClient) cattura già la codebase e la invia come JSON
    nel PreRequest. Questo provider wrappa quella logica server-side.
    """

    def __init__(self, files: dict[str, str] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._files = files or {}

    def snapshot(self) -> CodebaseSnapshot:
        return CodebaseSnapshot(files=self._files)