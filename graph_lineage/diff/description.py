"""Auto-generate experiment description from strategy and changed files."""

from __future__ import annotations


def generate_description(
    strategy: str,
    changed_files: list[str] | None = None,
    exp_id: str | None = None,
    model_id: str | None = None,
) -> str:
    """Generate a human-readable description for an experiment.

    Args:
        strategy: One of NEW, BRANCH, RETRY, MERGE.
        changed_files: List of filenames that changed (for BRANCH).
        exp_id: Parent experiment ID (for RETRY).
        model_id: Model ID (for RESUME).

    Returns:
        Formatted description string.
    """
    if strategy == "NEW":
        return "Initial experiment (base)"

    if strategy == "RETRY":
        return f"Retry of experiment {exp_id}" if exp_id else "Retry (same codebase)"

    if strategy == "RESUME":
        if model_id and exp_id:
            return f"Resume from model '{model_id}' (parent: {exp_id})"
        if model_id:
            return f"Resume from model '{model_id}'"
        return "Resume from model '{model_id}'" if model_id else "Resume from model"

    if strategy == "MERGE":
        return f"Model merge (parent: {exp_id})" if exp_id else "Model merge"

    if strategy == "BRANCH":
        if changed_files:
            files_str = ", ".join(changed_files)
            return f"files changed: {files_str}"
        return "Branch (codebase modified)"

    return f"Unknown strategy: {strategy}"
