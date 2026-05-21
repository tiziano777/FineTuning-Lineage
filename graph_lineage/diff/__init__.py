"""DiffManager infrastructure: snapshot capture, diff generation, change detection."""

from .snapshot import CodebaseSnapshot, capture_snapshot
from .differ import (
    compute_file_hash,
    compute_unified_diff,
    detect_changes,
    compute_snapshot_diff,
)
from .description import generate_description
from .reconstructor import apply_unified_diff, reconstruct_codebase

__all__ = [
    "CodebaseSnapshot",
    "capture_snapshot",
    "compute_file_hash",
    "compute_unified_diff",
    "detect_changes",
    "compute_snapshot_diff",
    "generate_description",
    "apply_unified_diff",
    "reconstruct_codebase",
]
