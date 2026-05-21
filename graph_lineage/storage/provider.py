"""Abstract base class for storage providers.

All storage operations go through this interface, decoupling
business logic from physical storage location (local/SSH/S3/etc).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class StorageProvider(ABC):
    """Abstract storage provider for filesystem-agnostic operations."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if path exists in storage."""

    @abstractmethod
    def read_text(self, path: str) -> str:
        """Read file as UTF-8 text. Raises FileNotFoundError if missing."""

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Read file as raw bytes. Raises FileNotFoundError if missing."""

    @abstractmethod
    def write_text(self, path: str, content: str) -> None:
        """Write UTF-8 text to path. Creates parent dirs if needed."""

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """Write raw bytes to path. Creates parent dirs if needed."""

    @abstractmethod
    def list_files(self, path: str, pattern: str = "*") -> list[str]:
        """List files matching glob pattern under path. Non-recursive."""

    @abstractmethod
    def walk(self, path: str, exclude_dotfiles: bool = True) -> Iterator[str]:
        """Recursively yield all file paths under path.

        Args:
            path: Root directory to walk.
            exclude_dotfiles: If True, skip files/dirs starting with '.'.
        """

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Check if path is directory."""

    @abstractmethod
    def is_writable(self, path: str) -> bool:
        """Check if path is writable (file or parent dir)."""

    @abstractmethod
    def backup(self, path: str) -> str | None:
        """Create backup copy of file. Returns backup path or None if file missing."""
