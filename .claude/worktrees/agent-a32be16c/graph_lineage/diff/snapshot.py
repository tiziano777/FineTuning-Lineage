"""CodebaseSnapshot: frozen Pydantic model capturing critical files."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field


CRITICAL_FILES: list[str] = [
    "config.yaml",
    "prepare.py",
    "train.py",
    "requirements.txt",
]

MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB limit per file


class CodebaseSnapshot(BaseModel):
    """Immutable snapshot of critical codebase files."""

    model_config = {"frozen": True}

    files: dict[str, str] = Field(default_factory=dict)

    def file_hash(self, filename: str) -> str:
        """Compute SHA-256 of a file's content with CRLF normalization."""
        content = self.files.get(filename, "")
        normalized = content.replace("\r\n", "\n")
        return hashlib.sha256(normalized.encode()).hexdigest()

    def hashes(self) -> dict[str, str]:
        """Return dict of all file hashes."""
        return {fname: self.file_hash(fname) for fname in self.files}


def capture_snapshot(codebase_root: Path) -> CodebaseSnapshot:
    """Read CRITICAL_FILES from disk into a frozen snapshot.

    Missing files are stored as empty string.
    Symlinks are not followed. Files exceeding MAX_FILE_SIZE are stored as empty.
    """
    resolved_root = codebase_root.resolve()
    files: dict[str, str] = {}

    for fname in CRITICAL_FILES:
        fpath = resolved_root / fname
        # Do not follow symlinks (T-03-01 mitigation)
        if fpath.is_symlink():
            files[fname] = ""
            continue
        if not fpath.is_file():
            files[fname] = ""
            continue
        # Prevent path traversal (T-03-01 mitigation)
        try:
            fpath.resolve().relative_to(resolved_root)
        except ValueError:
            files[fname] = ""
            continue
        # Max size check (T-03-03 mitigation)
        if fpath.stat().st_size > MAX_FILE_SIZE:
            files[fname] = ""
            continue
        files[fname] = fpath.read_text(encoding="utf-8", errors="replace")

    return CodebaseSnapshot(files=files)
