from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .server_config import ServerConfig

@dataclass
class ExecutionContext:
    """State passed from PRE to POST execution within a single run."""

    experiment_id: str
    strategy: str
    project_root: Path
    server_config: ServerConfig
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        """Alias concettuale per experiment_id (preparazione al dominio generico 'Run')."""
        return self.experiment_id
