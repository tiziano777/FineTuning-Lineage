"""RuleEngine: detect run type strategy based on config and codebase state."""

from __future__ import annotations

import re
import json
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
    changed_files: list[str] | None = None  # filenames that differ (for description)

class ModelIdMismatchError(Exception):
    """Raised when model_id changed between runs — user must fix or create new setup."""

    def __init__(self, actual_id: str, expected_id: str):
        self.actual_id = actual_id
        self.expected_id = expected_id
        super().__init__(
            f"model.model_id changed from '{expected_id}' to '{actual_id}'. "
            f"If resuming from a checkpoint of the same model, restore model_id to '{expected_id}'. "
            f"Otherwise, create a new setup to train '{actual_id}'."
        )

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
    2. checkpoint_resume_from explicitly set → RESUME
    3. model_uri changed to checkpoint path (auto-detect) → RESUME
    4. previous_experiment_id == id (explicit signal) → RETRY
    5. No parent experiment → NEW
    6. Compare hashes: all match → RETRY, any differ → BRANCH

    Blocking guard:
    - If model_id differs from parent → ModelIdMismatchError

    Args:
        config: Parsed LineageConfig.
        current_snapshot: Current codebase snapshot with file hashes.
        parent_experiment: Parent Experiment from DB, or None.

    Returns:
        RunTypeResult with strategy and relevant context.

    Raises:
        ModelIdMismatchError: If model_id changed between runs.
    """
    # 1. MERGE: model_merging is enabled
    if config.model_merging.enabled:
        return RunTypeResult(
            strategy="MERGE",
            parent_exp_id=parent_experiment.id if parent_experiment else None,
        )

    # 2. RESUME explicit: checkpoint_resume_from is set and looks like a checkpoint
    ckp_ref = config.experiment.checkpoint_resume_from
    if ckp_ref and _looks_like_checkpoint_id(ckp_ref):
        return RunTypeResult(
            strategy="RESUME",
            parent_exp_id=parent_experiment.id if parent_experiment else None,
            parent_ckp_id=ckp_ref,
        )

    # Guard: model_id mismatch detection (only if parent exists)
    current_model_id = str(config.model.get("model_id", "")).strip()
    if parent_experiment and parent_experiment.model_id:
        if current_model_id and current_model_id != parent_experiment.model_id:
            raise ModelIdMismatchError(
                actual_id=current_model_id,
                expected_id=parent_experiment.model_id,
            )

    # 3. RESUME auto-detect: model_uri changed and looks like a checkpoint
    if parent_experiment:
        current_model_uri = str(config.model.get("model_uri", "")).strip()
        parent_model_uri = parent_experiment.model_uri or ""
        if (
            current_model_uri
            and parent_model_uri
            and current_model_uri != parent_model_uri
            and _looks_like_checkpoint_id(current_model_uri)
        ):
            return RunTypeResult(
                strategy="RESUME",
                parent_exp_id=parent_experiment.id,
                parent_ckp_id=current_model_uri,
            )

    # 4. RETRY explicit: previous_experiment_id == id (user signal)
    exp = config.experiment
    if exp.previous_experiment_id and exp.id and exp.previous_experiment_id == exp.id:
        return RunTypeResult(
            strategy="RETRY",
            parent_exp_id=exp.id,
        )

    # 5. NEW: no parent experiment in DB
    if parent_experiment is None:
        return RunTypeResult(strategy="NEW")

    # 6. Compare codebase content to decide RETRY vs BRANCH
    # Quick check via content hash, then detailed diff if different
    current_hashes = current_snapshot.hashes()
    parent_snapshot = CodebaseSnapshot(files=json.loads(parent_experiment.codebase))
    parent_hashes = parent_snapshot.hashes()

    if current_hashes == parent_hashes:
        return RunTypeResult(
            strategy="RETRY",
            parent_exp_id=parent_experiment.id,
        )

    # BRANCH: codebase differs — compute diff patch and changed files list
    diff_patch = compute_snapshot_diff(parent_snapshot, current_snapshot)
    changed_files = sorted(diff_patch.keys())

    return RunTypeResult(
        strategy="BRANCH",
        parent_exp_id=parent_experiment.id,
        diff_patch=json.dumps(diff_patch),
        changed_files=json.dumps(changed_files),
    )
