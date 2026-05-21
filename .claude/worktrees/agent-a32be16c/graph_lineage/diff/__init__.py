"""DiffManager infrastructure: snapshot capture, diff generation, change detection."""

from .snapshot import CodebaseSnapshot, capture_snapshot
from .differ import (
    compute_file_hash,
    compute_unified_diff,
    detect_changes,
    compute_snapshot_diff,
)

__all__ = [
    "CodebaseSnapshot",
    "capture_snapshot",
    "compute_file_hash",
    "compute_unified_diff",
    "detect_changes",
    "compute_snapshot_diff",
]
