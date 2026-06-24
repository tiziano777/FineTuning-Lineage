"""RuleEngine: detect run type strategy based on config and codebase state."""

from __future__ import annotations
from typing import Dict
import logging
import re
import json
from dataclasses import dataclass

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.diff.differ import compute_snapshot_diff
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.diff.reconstructor import reconstruct_codebase
from graph_lineage.lineage.neo4j_ops import _find_experiment_by_id_async, _find_parent_experiment_id_async

logger = logging.getLogger(__name__)

# Pattern for checkpoint IDs: UUID or path-like with "checkpoint" in it
_CHECKPOINT_PATTERN = re.compile(
    r"(checkpoint|ckpt)[-_/]",
    re.IGNORECASE,
)

async def reconstruct_full_codebase_from_experiment(
    experiment_id: str
) -> CodebaseSnapshot:
    """
    Ricostruisce la codebase completa per un esperimento risalendo la catena.
    """
    chain = []
    current_id = experiment_id
    
    while True:
        exp = await _find_experiment_by_id_async(current_id)
        if not exp:
            raise ValueError(f"Experiment {current_id} not found")
        
        codebase = json.loads(exp.codebase)
        
        chain.append({
            "id": exp.id,
            "codebase": codebase,
            "base": exp.base
        })
        
        if exp.base:
            break
            
        # Trova il parent attraverso le relazioni
        parent_id = await _find_parent_experiment_id_async(current_id)
        if parent_id is None:
            break  # Non dovrebbe succedere se non è base, ma safety
            
        current_id = parent_id

    # Debug: stampa la chain prima e dopo il reverse
    print("Chain before reverse (current -> base):")
    for i, node in enumerate(chain):
        print(f"  {i}: id={node['id']}, base={node['base']}, strategy={node.get('strategy', 'N/A')}")
    
    chain.reverse()
    
    print("Chain after reverse (base -> current):")
    for i, node in enumerate(chain):
        print(f"  {i}: id={node['id']}, base={node['base']}, strategy={node.get('strategy', 'N/A')}")

    full_codebase = reconstruct_codebase(chain)
    return CodebaseSnapshot(files=full_codebase)

async def get_full_codebase_for_experiment(
    experiment: Experiment
) -> CodebaseSnapshot:
    """
    Ottiene la codebase completa per un esperimento.
    Se è base, usa direttamente la sua codebase.
    Se non è base, ricostruisce dalla catena.
    """
    if experiment.base:
        return CodebaseSnapshot(files=json.loads(experiment.codebase))
    else:
        return await reconstruct_full_codebase_from_experiment(experiment.id)


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

async def detect_run_type(
    config: LineageConfig,
    current_snapshot: CodebaseSnapshot,
    parent_experiment: Experiment | None,
) -> RunTypeResult:
    """Detect the run type strategy based on config and parent state.

    Decision order:
    1. model_merging.enabled → MERGE
    2. checkpoint_resume_from explicitly set → RESUME
    3. model_uri changed to checkpoint path (auto-detect) → RESUME
    4. No parent experiment → NEW
    5. base_experiment_id == experiment_id → BRANCH or RETRY (if codebase identical)
    6. base_experiment_id != experiment_id and codebase differs → BRANCH, else RETRY

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

    exp = config.experiment

    # 1. MERGE: model_merging is enabled
    if config.model_merging.enabled:
        return RunTypeResult(
            strategy="MERGE",
            parent_exp_id=parent_experiment.id if parent_experiment else None,
        )
    logger.info("model_merging not enabled, proceeding with run type detection")

    # 2. RESUME explicit: checkpoint_resume_from is set and looks like a checkpoint
    ckp_ref = config.experiment.checkpoint_resume_from
    if ckp_ref and _looks_like_checkpoint_id(ckp_ref):
        return RunTypeResult(
            strategy="RESUME",
            parent_exp_id=exp.id,
            parent_ckp_id=ckp_ref,
        )
    logger.info("checkpoint_resume_from not set or not a checkpoint, proceeding with run type detection")

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
    logger.info("model_uri not changed to checkpoint, proceeding with run type detection")

    # 4. NEW case: no parent experiment and not base
    if not parent_experiment and not exp.base:
            return RunTypeResult(strategy="NEW")

    logger.info("parent experiment: %s. and base: %s", parent_experiment.id if parent_experiment else None, exp.base)

    # 5. experiment is the BASE: RETRY vs BRANCH: parent experiment exists, check codebase
    # CURRENT HASHES:
    current_hashes = current_snapshot.hashes()
    import copy
    no_lineage_current_hashes = copy.deepcopy(current_hashes)
    no_lineage_current_hashes.pop(".lineage/experiment.yml", None)

    # 5. experiment is the BASE: RETRY vs BRANCH: parent experiment exists, check codebase
    if exp.base_experiment_id == exp.id: # Experiment is its own base, check if codebase matches previous run
        base = await _find_experiment_by_id_async(exp.base_experiment_id)
        previous_codebase_snapshot = CodebaseSnapshot(files=json.loads(base.codebase))
        previous_codebase_hashes = previous_codebase_snapshot.hashes()

        # drop lineage info from hashes for this comparison, since it will always differ but shouldn't trigger a BRANCH
        no_lineage_previous_hashes = copy.deepcopy(previous_codebase_hashes)
        no_lineage_previous_hashes.pop(".lineage/experiment.yml", None)


        if no_lineage_current_hashes == no_lineage_previous_hashes:
            logger.info("Codebase matches previous run, treating as RETRY")
            diff_patch = compute_snapshot_diff(previous_codebase_snapshot, current_snapshot)
            return RunTypeResult(
                strategy="RETRY",
                parent_exp_id=exp.id,
                diff_patch=diff_patch,
                changed_files=sorted(diff_patch.keys()),
            )
        else:
            logger.info("Codebase differs from previous run, treating as BRANCH")
            diff_patch = compute_snapshot_diff(previous_codebase_snapshot, current_snapshot)
            return RunTypeResult(
                strategy="BRANCH",
                parent_exp_id=exp.id,
                diff_patch=diff_patch,
                changed_files=sorted(diff_patch.keys()),
            )

    # EXPERIMENT IS NOT BASE: RETRY vs BRANCH: parent experiment exists, check codebase
    # 6. Compare codebase content to decide RETRY vs BRANCH
    # Quick check via content hash, then detailed diff if different
    
    # Snapshot of parent experiment's codebase
    parent_snapshot = await reconstruct_full_codebase_from_experiment(exp.id) # actual experiment is the new parent of this run

    parent_hashes = parent_snapshot.hashes()
    no_lineage_parent_hashes = copy.deepcopy(parent_hashes)
    no_lineage_parent_hashes.pop(".lineage/experiment.yml", None) 
    no_lineage_current_hashes = copy.deepcopy(current_hashes)
    no_lineage_current_hashes.pop(".lineage/experiment.yml", None)

    diff_patch = compute_snapshot_diff(old_snapshot= parent_snapshot, new_snapshot= current_snapshot) 

    logger.info("file changes: %s", set(sorted(no_lineage_current_hashes.keys())) - set(sorted(no_lineage_parent_hashes.keys())))
 
    if no_lineage_current_hashes == no_lineage_parent_hashes:
        return RunTypeResult(
            strategy="RETRY",
            parent_exp_id=exp.id,
            diff_patch=diff_patch,
            changed_files=sorted(diff_patch.keys()),
        )

    # BRANCH: codebase differs — compute diff patch and changed files list
    return RunTypeResult(
        strategy="BRANCH",
        parent_exp_id=exp.id,
        diff_patch=diff_patch,
        changed_files=sorted(diff_patch.keys())
    )
