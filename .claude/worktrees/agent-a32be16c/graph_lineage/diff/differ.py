"""Differ: unified diff generation, hash computation, change detection."""

from __future__ import annotations

import difflib
import hashlib

from .snapshot import CodebaseSnapshot


def compute_file_hash(content: str) -> str:
    """Compute SHA-256 of content after normalizing CRLF to LF."""
    normalized = content.replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode()).hexdigest()


def compute_unified_diff(old_content: str, new_content: str, filename: str) -> str:
    """Generate unified diff between old and new content.

    Returns empty string if contents are identical.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))

    if not diff_lines:
        return ""
    return "".join(diff_lines)


def detect_changes(old_hashes: dict[str, str], new_hashes: dict[str, str]) -> list[str]:
    """Return list of filenames where hash differs between old and new."""
    changed = []
    all_keys = set(old_hashes.keys()) | set(new_hashes.keys())
    for fname in sorted(all_keys):
        if old_hashes.get(fname) != new_hashes.get(fname):
            changed.append(fname)
    return changed


def compute_snapshot_diff(
    old_snapshot: CodebaseSnapshot,
    new_snapshot: CodebaseSnapshot,
) -> dict[str, str]:
    """Compute diffs between two snapshots, returning only changed files.

    Returns dict of {filename: unified_diff_string} for files that differ.
    """
    old_hashes = old_snapshot.hashes()
    new_hashes = new_snapshot.hashes()
    changed_files = detect_changes(old_hashes, new_hashes)

    result: dict[str, str] = {}
    for fname in changed_files:
        old_content = old_snapshot.files.get(fname, "")
        new_content = new_snapshot.files.get(fname, "")
        result[fname] = compute_unified_diff(old_content, new_content, fname)

    return result
