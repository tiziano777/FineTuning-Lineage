"""TrainingRunHandler: logica verticale di training (dominio AI).

Rifattorizzato per usare detect_branch_or_retry() dalla classe base,
eliminando la duplicazione dei punti 3-4 e i 4 pop() hardcoded.

Tutta la logica AI-specifica (RESUME, MERGE, model guards, CKP_DERIVED_FROM)
resta invariata e closed-world in questo modulo.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from typing import Any

from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.core.state_provider import GitOrExplicitCodebaseProvider
from graph_lineage.data_classes.neo4j.nodes.code.training.experiment import Experiment, StatusType, StrategyType
from graph_lineage.diff.description import generate_description
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.lineage.experiment_neo4j_ops import (
    create_base_experiment_node_with_edges,
    create_ckp_derived_from_edge,
    create_non_base_experiment_with_chain_edge,
    find_experiment_by_id,
    find_experiment_from_chain,
    find_model_by_name,
    find_parent_experiment_id,
    retrieve_ckp_by_experiment_id,
    retrieve_ckp_id_by_ckp_uri,
)
from graph_lineage.server.handlers.base import RunTypeHandler, RunTypeResult
from graph_lineage.server.schemas import PostRequest, PreRequest

logger = logging.getLogger(__name__)

# Edge type mapping per strategy — Experiment→Experiment edges only.
_STRATEGY_EXP_EDGE_MAP: dict[str, str] = {
    "BRANCH": "DERIVED_FROM",
    "RETRY": "RETRY_FROM",
    "MERGE": "MERGED_FROM",
    "RESUME": "RESUMED_FROM",
}


class ModelIdMismatchError(Exception):
    """Raised when model_id changed between runs."""

    def __init__(self, actual_id: str, expected_id: str):
        self.actual_id = actual_id
        self.expected_id = expected_id
        super().__init__(
            f"model.model_id changed from '{expected_id}' to '{actual_id}'. "
            f"If resuming from a checkpoint of the same model, restore model_id to '{expected_id}'. "
            f"Otherwise, create a new setup to train '{actual_id}'."
        )


class ModelDbMismatchError(Exception):
    """Raised when model_db changed between runs."""

    def __init__(
        self,
        db_model_name: str | None,
        db_model_uri: str | None,
        request_model_name: str,
        request_model_uri: str,
    ):
        super().__init__(
            f"model node in DB is '{db_model_name}' (URI: '{db_model_uri}') but in request we have "
            f"'{request_model_name}' (URI: '{request_model_uri}'). "
            f"If you have changed model uri, please update the model node by visiting the model page in the UI "
            f"and changing the uri. Otherwise, create a new setup to train '{request_model_name}' "
            f"(URI: '{request_model_uri}')."
        )


async def _reconstruct_full_codebase_from_experiment(experiment_id: str) -> CodebaseSnapshot:
    """Ricostruisce la codebase completa per un esperimento risalendo la catena."""
    chain = []
    current_id = experiment_id

    while True:
        exp = find_experiment_by_id(current_id)
        if not exp:
            raise ValueError(f"Experiment {current_id} not found")

        chain.append({"id": exp.id, "codebase": exp.codebase, "base": exp.base})

        if exp.base:
            break

        parent_id = find_parent_experiment_id(current_id)
        if parent_id is None:
            break
        current_id = parent_id

    chain.reverse()
    from graph_lineage.diff.reconstructor import reconstruct_codebase
    full_codebase = reconstruct_codebase(chain)
    return CodebaseSnapshot(files=full_codebase)


class TrainingRunHandler(RunTypeHandler):
    """Handler per run di tipo training.

    Usa detect_branch_or_retry() dalla classe base per i casi RETRY/BRANCH,
    eliminando la duplicazione e gli ignore pattern hardcoded.
    """

    run_type = "training"

    def __init__(self):
        # Usa il default StateProvider (ignora .lineage/*.yml automaticamente)
        super().__init__(state_provider=GitOrExplicitCodebaseProvider())

    async def detect(self, request: PreRequest) -> RunTypeResult:
        """Detect the run type strategy based on PreRequest.

        Logica AI-specifica (punti 0-2) invariata.
        Punti 3-4 (RETRY vs BRANCH) delegati a detect_branch_or_retry().
        """
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))

        exp = ExperimentConfig(
            name=request.experiment_name,
            uri=request.experiment_uri,
            id=request.experiment_id,
            previous_experiment_id=request.previous_experiment_id,
            base_experiment_id=request.base_experiment_id,
            base=request.base,
            model=request.model_id,
            component=request.component_id,
            recipe=request.recipe_id,
            experiment_type=request.run_type,
        )

        # 0. NEW case: no current experiment and not base
        if not exp.id and not exp.base:
            return RunTypeResult(strategy="NEW")

        # 1. MERGE: merging is enabled
        if request.merging:
            logger.info("merging enabled, proceeding with MERGE strategy")
            return RunTypeResult(strategy="MERGE")

        # Guard: model_uri mismatch detection (only if parent exists)
        current_model_uri = request.model_uri.strip() if request.model_uri else ""
        current_model_name = request.model_id.strip() if request.model_id else ""
        old_experiment = find_experiment_by_id(exp.id) if exp.id else None
        if old_experiment and old_experiment.model_uri:
            if current_model_uri and current_model_uri != old_experiment.model_uri:
                raise ModelIdMismatchError(
                    actual_id=current_model_uri,
                    expected_id=old_experiment.model_uri,
                )
        if current_model_name:
            db_model = find_model_by_name(current_model_name)
            db_model_name = db_model.model_name if db_model else None
            db_model_uri = db_model.uri if db_model else None
            if db_model_name != current_model_name and db_model_uri != current_model_uri:
                raise ModelDbMismatchError(
                    db_model_name=db_model_name,
                    db_model_uri=db_model_uri,
                    request_model_name=current_model_name,
                    request_model_uri=current_model_uri,
                )

        # 2.a) RESUME explicit: checkpoint_resume_from is set and looks like a checkpoint
        if request.checkpoint_resume_from:
            logger.info("checkpoint_resume_from set, proceeding with RESUME run type")
            candidates_ckps = retrieve_ckp_by_experiment_id(exp.id)
            for ckp in candidates_ckps:
                if ckp.uri == request.checkpoint_resume_from:
                    logger.info(
                        "checkpoint_resume_from explicitly set and found in previous experiment, treating as RESUME"
                    )
                    parent_snapshot = await _reconstruct_full_codebase_from_experiment(exp.id)
                    diff_patch = self.state_provider.diff(parent_snapshot, snapshot)
                    return RunTypeResult(
                        strategy="RESUME",
                        parent_run_id=exp.id,
                        parent_ckp_id=request.checkpoint_resume_from,
                        diff_patch=diff_patch,
                        changed_files=sorted(diff_patch.keys()),
                    )

            # 2.b) RESUME_v2: checkpoint_resume_from is set but not found in previous experiment,
            # find other ckp in the chain
            new_current_experiment = find_experiment_from_chain(
                exp.base_experiment_id, request.checkpoint_resume_from
            )
            parent_snapshot = await _reconstruct_full_codebase_from_experiment(new_current_experiment.id)
            diff_patch = self.state_provider.diff(parent_snapshot, snapshot)
            return RunTypeResult(
                strategy="RESUME",
                parent_run_id=new_current_experiment.id,
                parent_ckp_id=request.checkpoint_resume_from,
                diff_patch=diff_patch,
                changed_files=sorted(diff_patch.keys()),
            )

        # 3. experiment is the BASE: RETRY vs BRANCH (delegato a metodo condiviso)
        if exp.base_experiment_id == exp.id:
            base = find_experiment_by_id(exp.base_experiment_id)
            previous_codebase_snapshot = CodebaseSnapshot(files=base.codebase)
            return self.detect_branch_or_retry(
                current_snapshot=snapshot,
                parent_snapshot=previous_codebase_snapshot,
                parent_run_id=exp.id,
            )

        # 4. EXPERIMENT IS NOT BASE: RETRY vs BRANCH (delegato a metodo condiviso)
        parent_snapshot = await _reconstruct_full_codebase_from_experiment(exp.id)
        result = self.detect_branch_or_retry(
            current_snapshot=snapshot,
            parent_snapshot=parent_snapshot,
            parent_run_id=exp.id,
        )
        logger.info(
            "file changes: %s",
            set(result.changed_files or []),
        )
        return result

    def create_nodes(self, request: PreRequest, result: RunTypeResult) -> str:
        """Crea nodo Experiment e relativi edge nel grafo."""
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
        exp_id = str(uuid.uuid4())
        is_base = result.strategy == "NEW"

        auto_description = generate_description(
            strategy=result.strategy,
            changed_files=result.changed_files,
            exp_id=result.parent_run_id,
            ckp_id=result.parent_ckp_id,
        )
        description = request.description or auto_description

        # Aggiorna extra con la description per uso nel response
        result = replace(result, extra={**(result.extra or {}), "description": description})

        experiment = Experiment(
            id=exp_id,
            name=request.experiment_name,
            description=description,
            uri=request.experiment_uri or "",
            experiment_type=request.run_type,
            base=is_base,
            status=StatusType.RUNNING,
            strategy=StrategyType(result.strategy),
            model_id=request.model_id,
            codebase=json.dumps(snapshot.files) if is_base else json.dumps(result.diff_patch or {}),
            changed_files=result.changed_files or [],
            metrics_uri=None,
            model_uri=request.model_uri or None,
        )

        if is_base:
            logger.info(
                "Creating base experiment (atomic): exp_id=%s, recipe=%s, component=%s, model=%s",
                exp_id, request.recipe_id, request.component_id, request.model_id,
            )
            create_base_experiment_node_with_edges(
                exp=experiment,
                recipe_name=request.recipe_id,
                component_name=request.component_id,
                model_name=request.model_id,
            )
        else:
            edge_type = _STRATEGY_EXP_EDGE_MAP[result.strategy]
            edge_props: dict[str, Any] = {}
            if result.diff_patch:
                edge_props["diff_patch"] = str(result.diff_patch)

            logger.info(
                "Creating experiment with %s edge (atomic): exp_id=%s, parent_run_id=%s, props=%s",
                edge_type, exp_id, result.parent_run_id, edge_props,
            )
            create_non_base_experiment_with_chain_edge(
                exp=experiment,
                parent_exp_id=result.parent_run_id,
                strategy=edge_type,
                edge_properties=edge_props or None,
                parent_ckp_uri=result.parent_ckp_id if result.strategy == "RESUME" else None,
            )

        return exp_id

    def on_post(self, request: PostRequest) -> None:
        """Crea arco CKP_DERIVED_FROM per strategia RESUME."""
        if (
            request.status == StatusType.COMPLETED
            and request.strategy == StrategyType.RESUME
            and request.checkpoint_resume_from
        ):
            old_checkpoint = retrieve_ckp_id_by_ckp_uri(request.checkpoint_resume_from)
            new_ckps = retrieve_ckp_by_experiment_id(request.experiment_id)
            if new_ckps:
                first_ckp = None
                min_epoch = 0
                for ckp in new_ckps:
                    if min_epoch == 0 or ckp.epoch < min_epoch:
                        min_epoch = ckp.epoch
                        first_ckp = ckp

                if first_ckp and old_checkpoint:
                    logger.info(
                        "Creating CKP_DERIVED_FROM edge: base_ckp_id=%s, new_ckp_id=%s",
                        old_checkpoint, first_ckp.id,
                    )
                    create_ckp_derived_from_edge(base_ckp_id=old_checkpoint, new_ckp_id=first_ckp.id)