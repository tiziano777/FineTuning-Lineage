"""RuleEngine: detect run type strategy based on config and codebase state."""

from __future__ import annotations

import re
from dataclasses import dataclass

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.diff.differ import compute_snapshot_diff
from graph_lineage.diff.snapshot import CodebaseSnapshot

# Pattern for checkpoint IDs: UUID or path-like with "checkpoint" in it
_CHECKPOINT_PATTERN = re.compile(
    r"(checkpoint|ckpt)[-_/]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RunTypeResult:
    """Result of run type detection."""

    strategy: str  # NEW | RETRY | BRANCH | RESUME | MERGE
    parent_exp_id: str | None = None
    parent_ckp_id: str | None = None  # only for RESUME
    diff_patch: dict[str, str] | None = None  # only for BRANCH


def _looks_like_checkpoint_id(value: str) -> bool:
    """Check if a string looks like a checkpoint reference."""
    return bool(_CHECKPOINT_PATTERN.search(value))


def detect_run_type(
    config: LineageConfig,
    current_snapshot: CodebaseSnapshot,
    parent_experiment: Experiment | None,
) -> RunTypeResult:
    """Detect the run type strategy based on config and parent state.

    Decision order:
    1. model_merging.enabled → MERGE
    2. checkpoint_resume_from set → RESUME
    3. previous_experiment_id == id (explicit signal) → RETRY
    4. No parent experiment → NEW
    5. Compare hashes: all match → RETRY, any differ → BRANCH

    Args:
        config: Parsed LineageConfig.
        current_snapshot: Current codebase snapshot with file hashes.
        parent_experiment: Parent Experiment from DB, or None.

    Returns:
        RunTypeResult with strategy and relevant context.
    """
    # 1. MERGE: model_merging is enabled
    if config.model_merging.enabled:
        return RunTypeResult(
            strategy="MERGE",
            parent_exp_id=parent_experiment.id if parent_experiment else None,
        )

    # 2. RESUME: checkpoint_resume_from is set and looks like a checkpoint
    ckp_ref = config.experiment.checkpoint_resume_from
    if ckp_ref and _looks_like_checkpoint_id(ckp_ref):
        return RunTypeResult(
            strategy="RESUME",
            parent_exp_id=parent_experiment.id if parent_experiment else None,
            parent_ckp_id=ckp_ref,
        )

    # 3. RETRY explicit: previous_experiment_id == id (user signal)
    exp = config.experiment
    if exp.previous_experiment_id and exp.id and exp.previous_experiment_id == exp.id:
        return RunTypeResult(
            strategy="RETRY",
            parent_exp_id=exp.id,
        )

    # 4. NEW: no parent experiment in DB
    if parent_experiment is None:
        return RunTypeResult(strategy="NEW")

    # 5. Compare hashes to decide RETRY vs BRANCH
    current_hashes = current_snapshot.hashes()
    parent_hashes = {
        "config.yaml": parent_experiment.config_hash,
        "prepare.py": parent_experiment.prepare_hash,
        "train.py": parent_experiment.train_hash,
        "requirements.txt": parent_experiment.requirements_hash,
    }

    if current_hashes == parent_hashes:
        return RunTypeResult(
            strategy="RETRY",
            parent_exp_id=parent_experiment.id,
        )

    # BRANCH: hashes differ — compute diff patch
    # Build a minimal parent snapshot from hashes (we only need hashes for detection,
    # but diff_patch needs the actual content from parent codebase)
    parent_snapshot = CodebaseSnapshot(files=parent_experiment.codebase)
    diff_patch = compute_snapshot_diff(parent_snapshot, current_snapshot)

    return RunTypeResult(
        strategy="BRANCH",
        parent_exp_id=parent_experiment.id,
        diff_patch=diff_patch,
    )
