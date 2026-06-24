"""CodebaseSnapshot: frozen Pydantic model capturing project files for lineage tracking.

Scan rules:
- Root level: *.py, *.txt, *.yml, *.yaml
- modules/ folder: recursive *.py, *.yml, *.yaml
- .lineage/ folder: included (experiment.yml, server.yml, etc.)
- All other dot-files/dot-folders (., .venv, .cache, .env, etc.): EXCLUDED
- Max 10MB per file: blocking error if exceeded
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Extensions tracked at root level
_ROOT_EXTENSIONS: set[str] = {".py", ".txt", ".yml", ".yaml"}

# Extensions tracked inside modules/
_MODULE_EXTENSIONS: set[str] = {".py", ".yml", ".yaml"}

MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB


class FileTooLargeError(Exception):
    """Raised when a tracked file exceeds MAX_FILE_SIZE."""

    def __init__(self, filepath: Path, size: int):
        self.filepath = filepath
        self.size = size
        super().__init__(
            f"File '{filepath}' is {size / (1024*1024):.1f}MB which exceeds the "
            f"maximum allowed size of {MAX_FILE_SIZE / (1024*1024):.0f}MB. "
            f"Move large files outside the project root or add them to a dot-folder "
            f"(e.g., .data/) to exclude them from lineage tracking."
        )


class CodebaseSnapshot(BaseModel):
    """Immutable snapshot of project codebase files."""

    model_config = {"frozen": True}

    files: dict[str, str] = Field(default_factory=dict)

    def file_hash(self, filename: str) -> str:
        """Compute SHA-256 of a file's content with CRLF normalization."""
        content = self.files.get(filename, "")
        normalized = content.replace("\r\n", "\n")
        return hashlib.sha256(normalized.encode()).hexdigest()

    def hashes(self) -> dict[str, str]:
        """Return dict of {filename: sha256_hash} for all files."""
        return {fname: self.file_hash(fname) for fname in self.files}

    def content_hash(self) -> str:
        """Single hash representing the entire snapshot (for quick equality check)."""
        combined = "".join(
            f"{k}:{self.file_hash(k)}" for k in sorted(self.files.keys())
        )
        return hashlib.sha256(combined.encode()).hexdigest()

def _is_dot_path(path: Path, root: Path) -> bool:
    """Check if any part of the relative path starts with '.' (except .lineage)."""
    rel = path.relative_to(root)
    for part in rel.parts:
        if part.startswith(".") and part != ".lineage":
            return True
    return False

def _read_file_safe(filepath: Path) -> str:
    """Read file content with safety checks.

    Raises:
        FileTooLargeError: if file exceeds MAX_FILE_SIZE.
    """
    if filepath.is_symlink():
        return ""

    size = filepath.stat().st_size
    if size > MAX_FILE_SIZE:
        raise FileTooLargeError(filepath, size)

    return filepath.read_text(encoding="utf-8", errors="replace")

def capture_snapshot(codebase_root: Path) -> CodebaseSnapshot:
    """Scan project and capture all tracked files into a frozen snapshot.

    Scan rules:
    1. Root level: files matching _ROOT_EXTENSIONS (*.py, *.txt, *.yml, *.yaml)
    2. modules/ folder: recursive scan for _MODULE_EXTENSIONS (*.py, *.yml, *.yaml)
    3. .lineage/ folder: all files (experiment.yml, server.yml, etc.)
    4. Skip all other dot-files and dot-folders
    5. File > 10MB → FileTooLargeError (blocking)

    Args:
        codebase_root: Path to the project root directory.

    Returns:
        CodebaseSnapshot with relative paths as keys.

    Raises:
        FileTooLargeError: If any tracked file exceeds MAX_FILE_SIZE.
    """
    resolved_root = codebase_root.resolve()
    files: dict[str, str] = {}

    # 1. Root-level files (non-recursive, matching extensions)
    for item in sorted(resolved_root.iterdir()):
        if item.is_file() and not item.name.startswith("."):
            if item.suffix in _ROOT_EXTENSIONS:
                # Path traversal check
                try:
                    item.resolve().relative_to(resolved_root)
                except ValueError:
                    continue
                rel_key = item.name
                files[rel_key] = _read_file_safe(item)

    # 2. modules/ folder (recursive)
    modules_dir = resolved_root / "modules"
    if modules_dir.is_dir():
        for item in sorted(modules_dir.rglob("*")):
            if item.is_file() and not _is_dot_path(item, resolved_root):
                if item.suffix in _MODULE_EXTENSIONS:
                    try:
                        item.resolve().relative_to(resolved_root)
                    except ValueError:
                        continue
                    rel_key = str(item.relative_to(resolved_root))
                    files[rel_key] = _read_file_safe(item)

    # 3. .lineage/ folder (all files)
    lineage_dir = resolved_root / ".lineage"
    if lineage_dir.is_dir():
        for item in sorted(lineage_dir.rglob("*")):
            if item.is_file():
                try:
                    item.resolve().relative_to(resolved_root)
                except ValueError:
                    continue
                rel_key = str(item.relative_to(resolved_root))
                files[rel_key] = _read_file_safe(item)

    return CodebaseSnapshot(files=files)
