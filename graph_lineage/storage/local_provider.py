"""Local filesystem storage provider.

Implements StorageProvider for local/mounted filesystems.
Handles: local paths, NFS mounts, shared mounts.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterator

from graph_lineage.storage.provider import StorageProvider


class LocalStorageProvider(StorageProvider):
    """Storage provider for local filesystem operations."""

    def __init__(self, base_path: str | None = None):
        """Initialize with optional base path prefix.

        Args:
            base_path: If set, all paths are resolved relative to this.
                       If None, paths are used as-is.
        """
        self._base = Path(base_path) if base_path else None

    def _resolve(self, path: str) -> Path:
        """Resolve path against base_path if set."""
        p = Path(path)
        if self._base and not p.is_absolute():
            return self._base / p
        return p

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def read_text(self, path: str) -> str:
        resolved = self._resolve(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")
        return resolved.read_text(encoding="utf-8")

    def read_bytes(self, path: str) -> bytes:
        resolved = self._resolve(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")
        return resolved.read_bytes()

    def write_text(self, path: str, content: str) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    def write_bytes(self, path: str, data: bytes) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)

    def list_files(self, path: str, pattern: str = "*") -> list[str]:
        resolved = self._resolve(path)
        if not resolved.is_dir():
            return []
        return sorted(str(f) for f in resolved.glob(pattern) if f.is_file())

    def walk(self, path: str, exclude_dotfiles: bool = True) -> Iterator[str]:
        resolved = self._resolve(path)
        if not resolved.is_dir():
            return

        for root, dirs, files in os.walk(resolved):
            if exclude_dotfiles:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                files = [f for f in files if not f.startswith(".")]

            for filename in sorted(files):
                yield os.path.join(root, filename)

    def is_dir(self, path: str) -> bool:
        return self._resolve(path).is_dir()

    def is_writable(self, path: str) -> bool:
        resolved = self._resolve(path)
        if resolved.exists():
            return os.access(resolved, os.W_OK)
        # Check parent dir
        parent = resolved.parent
        return parent.exists() and os.access(parent, os.W_OK)

    def backup(self, path: str) -> str | None:
        resolved = self._resolve(path)
        if not resolved.exists():
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = resolved.with_suffix(f".bak.{timestamp}{resolved.suffix}")
        shutil.copy2(resolved, backup_path)
        return str(backup_path)
