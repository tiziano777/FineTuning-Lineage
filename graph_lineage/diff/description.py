"""Auto-generate experiment description from strategy and changed files."""

from __future__ import annotations


def generate_description(
    strategy: str,
    changed_files: list[str] | None = None,
    exp_id: str | None = None,
    ckp_id: str | None = None,
) -> str:
    """Generate a human-readable description for an experiment.

    Args:
        strategy: One of NEW, BRANCH, RETRY, RESUME, MERGE.
        changed_files: List of filenames that changed (for BRANCH).
        exp_id: Parent experiment ID (for RETRY/RESUME).
        ckp_id: Checkpoint ID or model_uri (for RESUME).

    Returns:
        Formatted description string.
    """
    if strategy == "NEW":
        return "Initial experiment (base)"

    if strategy == "RETRY":
        return f"Retry of experiment {exp_id}" if exp_id else "Retry (same codebase)"

    if strategy == "RESUME":
        if ckp_id and exp_id:
            return f"Resume from checkpoint '{ckp_id}' (parent: {exp_id})"
        if ckp_id:
            return f"Resume from checkpoint '{ckp_id}'"
        return "Resume from checkpoint"

    if strategy == "MERGE":
        return f"Model merge (parent: {exp_id})" if exp_id else "Model merge"

    if strategy == "BRANCH":
        if changed_files:
            files_str = ", ".join(changed_files)
            return f"files changed: {files_str}"
        return "Branch (codebase modified)"

    return f"Unknown strategy: {strategy}"
