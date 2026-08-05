"""Codebase reconstruction from lineage chain (base snapshot + sequential diffs)."""

from __future__ import annotations

import re

MAX_CHAIN_DEPTH: int = 200

import subprocess
import tempfile
import os

def apply_unified_diff(original: str, patch: str) -> str:
    if not patch:
        return original
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.orig', delete=False) as f:
        f.write(original)
        orig_path = f.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
        f.write(patch)
        patch_path = f.name
    
    try:
        result = subprocess.run(
            ['patch', '--output=-', orig_path, patch_path],
            capture_output=True, text=True
        )
        return result.stdout
    finally:
        os.unlink(orig_path)
        os.unlink(patch_path)

def _parse_hunks(patch: str) -> list[tuple[int, int, list[str]]]:
    """Parse unified diff into hunks.

    Returns list of (start_line_0indexed, old_line_count, new_lines).
    """
    hunks: list[tuple[int, int, list[str]]] = []
    lines = patch.splitlines(keepends=True)

    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match:
            old_start = int(match.group(1)) - 1  # Convert to 0-indexed
            old_count = int(match.group(2)) if match.group(2) is not None else 1
            i += 1

            new_lines: list[str] = []
            consumed_old = 0

            while i < len(lines) and consumed_old < old_count:
                hline = lines[i]
                if hline.startswith(" "):
                    new_lines.append(hline[1:])
                    consumed_old += 1
                elif hline.startswith("-"):
                    consumed_old += 1
                elif hline.startswith("+"):
                    new_lines.append(hline[1:])
                elif hline.startswith("@@") or hline.startswith("---") or hline.startswith("+++"):
                    break
                else:
                    # Context line without prefix (shouldn't happen in valid diff)
                    new_lines.append(hline)
                    consumed_old += 1
                i += 1

            # Consume any remaining + lines after old lines exhausted
            while i < len(lines):
                hline = lines[i]
                if hline.startswith("+") and not hline.startswith("+++"):
                    new_lines.append(hline[1:])
                    i += 1
                else:
                    break

            hunks.append((old_start, old_count, new_lines))
        else:
            i += 1

    return hunks

def reconstruct_codebase(chain: list[dict[str, dict[str, str]]]) -> dict[str, str]:
    """Reconstruct codebase state from a lineage chain.

    Args:
        chain: List where chain[0]["codebase"] is the base snapshot (filename -> content)
               and chain[1..n]["codebase"] are diffs (filename -> unified_diff).

    Returns:
        Reconstructed file contents dict.

    Raises:
        ValueError: If chain exceeds MAX_CHAIN_DEPTH.
    """
    if len(chain) > MAX_CHAIN_DEPTH:
        raise ValueError(
            f"Chain depth {len(chain)} exceeds maximum allowed depth {MAX_CHAIN_DEPTH}"
        )

    current = dict(chain[0]["codebase"])

    for entry in chain[1:]:
        diffs = entry["codebase"]
        for filename, patch in diffs.items():
            original = current.get(filename, "")
            current[filename] = apply_unified_diff(original, patch)

    return current
