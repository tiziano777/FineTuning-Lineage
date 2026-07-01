"""RuleEngine: detect run type strategy based on request."""

from __future__ import annotations
import copy
import logging
import re
import json
from dataclasses import dataclass

from graph_lineage.server.schemas import PreRequest
from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.diff.differ import compute_snapshot_diff
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.diff.reconstructor import reconstruct_codebase
from graph_lineage.lineage.neo4j_ops import find_experiment_by_id, find_parent_experiment_id, retrieve_ckp_by_experiment_id, find_experiment_from_chain

logger = logging.getLogger(__name__)

# Pattern for checkpoint IDs: UUID or path-like with "checkpoint" in it
_CHECKPOINT_PATTERN = re.compile(
    r"(checkpoint|ckpt|ckp)[-_/]",
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
        exp = find_experiment_by_id(current_id)
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
        parent_id = find_parent_experiment_id(current_id)
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

async def detect_run_type(
    request: PreRequest
) -> RunTypeResult:
    """Detect the run type strategy based on PreRequest.

    Decision order:
    0. No current experiment → NEW
    1. if merging enabled → MERGE
    2. checkpoint_resume_from explicitly set → RESUME
    3. model_uri changed to checkpoint path (auto-detect) → RESUME
    4. base_experiment_id == experiment_id → BRANCH or RETRY (if codebase identical)
    5. base_experiment_id != experiment_id and codebase differs → BRANCH, else RETRY

    Blocking guard:
        - If model_id differs from parent → ModelIdMismatchError

    Args:
        config: PreRequest object containing the request data.
        current_snapshot: Current codebase snapshot with file hashes.

    Returns:
        RunTypeResult with strategy and relevant context.

    Raises:
        ModelIdMismatchError: If model_id changed between runs.
    """
    # CURRENT EXPERIMENT STATE, exp IS THE NEW OLD EXPERIMENT (PARENT) FOR THIS RUN
    exp = ExperimentConfig(name= request.experiment_name,
                uri= request.experiment_uri,
                id= request.experiment_id,
                previous_experiment_id= request.previous_experiment_id,
                base_experiment_id= request.base_experiment_id,   
                base= request.base,
                model_id= request.model_id,
                component_id= request.component_id,
                recipe_id= request.recipe_id,)
    
    snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
    # CURRENT HASHES:
    current_hashes = snapshot.hashes()

    # 0. NEW case: no current experiment and not base
    if not exp.id and not exp.base:
            return RunTypeResult(strategy="NEW")

    # 1. MERGE: merging is enabled
    if request.merging:
        logger.info("merging enabled, proceeding with MERGE strategy")
        return RunTypeResult(
            strategy="MERGE",
        )

    # 2.a) RESUME explicit: checkpoint_resume_from is set and looks like a checkpoint
    if request.checkpoint_resume_from:
        logger.info("checkpoint_resume_from set, proceeding with RESUME run type")
        # retrive ckp from previous experiment if parent exists:
        candidates_ckps= retrieve_ckp_by_experiment_id(exp.id)
        for ckp in candidates_ckps:
            if ckp.uri == request.checkpoint_resume_from:
                logger.info("checkpoint_resume_from explicitly set and found in previous experiment, treating as RESUME")
                # adesso dobbiamo vedere se ci sono diff!
                # Snapshot of parent experiment's codebase
                parent_snapshot = await reconstruct_full_codebase_from_experiment(exp.id) # actual experiment is the new parent of this run
                parent_hashes = parent_snapshot.hashes()
                no_lineage_parent_hashes = copy.deepcopy(parent_hashes)
                no_lineage_parent_hashes.pop(".lineage/experiment.yml", None) 
                no_lineage_current_hashes = copy.deepcopy(current_hashes)
                no_lineage_current_hashes.pop(".lineage/experiment.yml", None)
                diff_patch = compute_snapshot_diff(old_snapshot= parent_snapshot, new_snapshot= snapshot) 

                return RunTypeResult(
                    strategy="RESUME",
                    parent_exp_id=exp.id,
                    parent_ckp_id=request.checkpoint_resume_from,
                    diff_patch=diff_patch,
                    changed_files=sorted(diff_patch.keys())
                )
        
        # 2.b) RESUME_v2 checkpoint_resume_from is set but not found in previous experiment, find other ckp in the chain
        new_current_experiment = find_experiment_from_chain(exp.base_experiment_id, request.checkpoint_resume_from)
        parent_snapshot = await reconstruct_full_codebase_from_experiment(new_current_experiment.id) # actual experiment is the new parent of this run
        parent_hashes = parent_snapshot.hashes()
        no_lineage_parent_hashes = copy.deepcopy(parent_hashes)
        no_lineage_parent_hashes.pop(".lineage/experiment.yml", None) 
        no_lineage_current_hashes = copy.deepcopy(current_hashes)
        no_lineage_current_hashes.pop(".lineage/experiment.yml", None)
        diff_patch = compute_snapshot_diff(old_snapshot= parent_snapshot, new_snapshot= snapshot) 
        return RunTypeResult(
            strategy="RESUME",
            parent_exp_id=new_current_experiment.id,
            parent_ckp_id=request.checkpoint_resume_from,
            diff_patch=diff_patch,
            changed_files=sorted(diff_patch.keys())
        )
    
    # Guard: model_uri mismatch detection (only if parent exists)
    current_model_uri = request.model_uri.strip()
    old_experiment = find_experiment_by_id(exp.id)
    if old_experiment and old_experiment.model_uri:
        if current_model_uri and current_model_uri != old_experiment.model_uri:
            raise ModelIdMismatchError(
                actual_id=current_model_uri,
                expected_id=old_experiment.model_uri,
            )

    # 3. experiment is the BASE: RETRY vs BRANCH: parent experiment exists, check codebase
    no_lineage_current_hashes = copy.deepcopy(current_hashes)
    no_lineage_current_hashes.pop(".lineage/experiment.yml", None)

    # 4. experiment is the BASE: RETRY vs BRANCH: parent experiment exists, check codebase
    if exp.base_experiment_id == exp.id: # Experiment is its own base, check if codebase matches previous run
        base = find_experiment_by_id(exp.base_experiment_id)
        previous_codebase_snapshot = CodebaseSnapshot(files=json.loads(base.codebase))
        previous_codebase_hashes = previous_codebase_snapshot.hashes()

        # drop lineage info from hashes for this comparison, since it will always differ but shouldn't trigger a BRANCH
        no_lineage_previous_hashes = copy.deepcopy(previous_codebase_hashes)
        no_lineage_previous_hashes.pop(".lineage/experiment.yml", None)


        if no_lineage_current_hashes == no_lineage_previous_hashes:
            logger.info("Codebase matches previous run, treating as RETRY")
            diff_patch = compute_snapshot_diff(previous_codebase_snapshot, snapshot)
            return RunTypeResult(
                strategy="RETRY",
                parent_exp_id=exp.id,
                diff_patch=diff_patch,
                changed_files=sorted(diff_patch.keys()),
            )
        else:
            logger.info("Codebase differs from previous run, treating as BRANCH")
            diff_patch = compute_snapshot_diff(previous_codebase_snapshot, snapshot)
            return RunTypeResult(
                strategy="BRANCH",
                parent_exp_id=exp.id,
                diff_patch=diff_patch,
                changed_files=sorted(diff_patch.keys()),
            )

    # EXPERIMENT IS NOT BASE: RETRY vs BRANCH: parent experiment exists, check codebase
    # 5. Compare codebase content to decide RETRY vs BRANCH
    # Quick check via content hash, then detailed diff if different
    
    # Snapshot of parent experiment's codebase
    parent_snapshot = await reconstruct_full_codebase_from_experiment(exp.id) # actual experiment is the new parent of this run

    parent_hashes = parent_snapshot.hashes()
    no_lineage_parent_hashes = copy.deepcopy(parent_hashes)
    no_lineage_parent_hashes.pop(".lineage/experiment.yml", None) 
    no_lineage_current_hashes = copy.deepcopy(current_hashes)
    no_lineage_current_hashes.pop(".lineage/experiment.yml", None)

    diff_patch = compute_snapshot_diff(old_snapshot= parent_snapshot, new_snapshot= snapshot) 

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
