"""Description message generation from changed files and strategy."""

from __future__ import annotations

from graph_lineage.config_file.commit_msg.loader import load_messages


def generate_description(
    changed_files: list[str] | None = None,
    strategy: str = "BRANCH",
    messages: dict | None = None,
    exp_id: str | None = None,
    ckp_id: str | None = None,
) -> str:
    """Generate a human-readable description for a lineage entry.

    Args:
        changed_files: List of filenames that changed between snapshots.
        strategy: One of BRANCH, RETRY, RESUME.
        messages: Optional pre-loaded message templates dict.
        exp_id: Experiment ID (required for RETRY/RESUME).
        ckp_id: Checkpoint ID (required for RESUME).

    Returns:
        Formatted description string.
    """
    if messages is None:
        messages = load_messages()

    if changed_files is None:
        changed_files = []

    if strategy == "RETRY":
        return messages["retry"].format(exp_id=exp_id)

    if strategy == "RESUME":
        return messages["resume"].format(exp_id=exp_id, ckp_id=ckp_id)

    if not changed_files:
        return messages["no_changes"]

    critical_files = messages.get("critical_files", [])
    critical_changed = sorted(f for f in changed_files if f in critical_files)

    if not critical_changed:
        return messages["non_critical_changes"]

    return ", ".join(
        messages["file_modified"].format(filename=f) for f in critical_changed
    )
