"""TrainingRunHandler: logica verticale di training (dominio AI).

REFACTOR v3:
- Rimosso checkpoint_resume_from (deprecato).
- RESUME e' ora model-switch: nuovo base experiment, nessun ponte CKP.
- Model constraint check, blocking/non-blocking, e CKP promotion sono TUTTI qui.
- Il server endpoint e' un thin dispatcher: chiama detect() e create_nodes().
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from typing import Any

from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.core.state_provider import GitOrExplicitCodebaseProvider
from graph_lineage.data_classes.neo4j.nodes.code.training.experiment import Experiment
from graph_lineage.data_classes.neo4j.nodes.base.enum.status_type import StatusType
from graph_lineage.data_classes.neo4j.nodes.code.enum.strategy_type import StrategyType
from graph_lineage.diff.description import generate_description
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.lineage.experiment_neo4j_ops import (
    create_base_experiment_node_with_edges,
    create_non_base_experiment_with_chain_edge,
    find_experiment_by_id,
    find_model_by_name,
    find_parent_experiment_id,
    promote_checkpoint_to_model,
    retrieve_ckp_id_by_ckp_uri,
)
from graph_lineage.server.handlers.base import RunTypeHandler, RunTypeResult
from graph_lineage.server.schemas import PostRequest, PreRequest

logger = logging.getLogger(__name__)

# Edge type mapping per strategy — Experiment->Experiment edges only.
_STRATEGY_EXP_EDGE_MAP: dict[str, str] = {
    "BRANCH": "DERIVED_FROM",
    "RETRY": "RETRY_FROM",
    "MERGE": "MERGED_FROM",
}


class ModelIdMismatchError(Exception):
    """Raised when model constraint is broken and blocking=True."""
    pass


class ModelDbMismatchError(Exception):
    """DEPRECATED: kept for backward-compat server catch."""
    pass


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

    Responsabilita': decidere la strategy (NEW, BRANCH, RETRY, MERGE, RESUME)
    e creare i nodi Experiment corrispondenti.
    Il model switch (RESUME) e' gestito interamente qui.
    """

    run_type = "training"

    def __init__(self):
        super().__init__(state_provider=GitOrExplicitCodebaseProvider())

    async def detect(self, request: PreRequest) -> RunTypeResult:
        """Detect the run type strategy.

        Strategie:
        - NEW: nessun experiment corrente, non e' base.
        - MERGE: flag merging attivo.
        - RESUME: model mismatch (model switch) -> nuovo base experiment.
        - BRANCH / RETRY: confronto diff tra codebase corrente e parent.
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

        # 0. NEW: nessun experiment corrente e non e' base
        if not exp.id and not exp.base:
            logger.info("No experiment id and not base — strategy=NEW")
            return RunTypeResult(strategy="NEW")

        # 1. MERGE: merging e' attivo
        if request.merging:
            logger.info("Merging enabled — strategy=MERGE")
            return RunTypeResult(strategy="MERGE")

        # 2. MODEL CONSTRAINT CHECK (gestito interamente nell'handler)
        current_model_uri = request.model_uri.strip() if request.model_uri else ""
        current_model_name = request.model_id.strip() if request.model_id else ""

        parent_experiment = find_experiment_by_id(exp.previous_experiment_id) if exp.previous_experiment_id else None

        model_mismatch = False
        if parent_experiment:
            parent_model_id = getattr(parent_experiment, 'model_id', None)
            parent_model_uri = getattr(parent_experiment, 'model_uri', None)
            if current_model_name and current_model_name != parent_model_id:
                model_mismatch = True
            if current_model_uri and current_model_uri != parent_model_uri:
                model_mismatch = True

        # Verifica coerenza con DB (model node esistente)
        if current_model_name:
            db_model = find_model_by_name(current_model_name)
            if db_model is None:
                model_mismatch = True
            else:
                db_model_uri = getattr(db_model, 'uri', None)
                if current_model_uri and db_model_uri and current_model_uri != db_model_uri:
                    model_mismatch = True

        if model_mismatch:
            logger.warning(
                "MODEL MISMATCH: parent=(%s, %s) vs request=(%s, %s), blocking=%s",
                getattr(parent_experiment, 'model_id', None),
                getattr(parent_experiment, 'model_uri', None),
                current_model_name, current_model_uri,
                request.blocking,
            )
            if request.blocking:
                raise ModelIdMismatchError(
                    f"Model constraint broken: parent model "
                    f"({getattr(parent_experiment, 'model_id', None)}, {getattr(parent_experiment, 'model_uri', None)}) "
                    f"differs from request model ({current_model_name}, {current_model_uri}). "
                    f"Instantiate a new experiment with the new model."
                )
            # Non-blocking: RESUME (model switch) -> nuovo base experiment
            logger.info("blocking=False — switching to RESUME strategy (new base experiment)")
            return RunTypeResult(
                strategy="RESUME",
                parent_run_id=parent_experiment.id if parent_experiment else exp.previous_experiment_id,
                parent_ckp_id=None,
                diff_patch=None,
                changed_files=[],
            )

        # 3. BASE experiment: RETRY vs BRANCH
        if exp.base_experiment_id == exp.id:
            base = find_experiment_by_id(exp.base_experiment_id)
            if base is None:
                raise ValueError(f"Base experiment {exp.base_experiment_id} not found")
            previous_codebase_snapshot = CodebaseSnapshot(files=base.codebase)
            return self.detect_branch_or_retry(
                current_snapshot=snapshot,
                parent_snapshot=previous_codebase_snapshot,
                parent_run_id=exp.id,
            )

        # 4. NON-BASE experiment: RETRY vs BRANCH
        parent_snapshot = await _reconstruct_full_codebase_from_experiment(exp.id)
        result = self.detect_branch_or_retry(
            current_snapshot=snapshot,
            parent_snapshot=parent_snapshot,
            parent_run_id=exp.id,
        )
        logger.info("File changes detected: %s", set(result.changed_files or []))
        return result

    def create_nodes(self, request: PreRequest, result: RunTypeResult) -> str:
        """Crea nodo Experiment e relativi edge nel grafo.

        - NEW / RESUME -> base experiment, salva TUTTA la codebase, atomic con Recipe/Component/Model.
        - BRANCH / RETRY / MERGE -> non-base, salva DIFF patch, edge verso parent.
        - Per RESUME: promuove CKP a Model se necessario, cambia nome in derived__{parent}, traccia resumed_from.
        """
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
        exp_id = str(uuid.uuid4())
        is_base = result.strategy in ("NEW", "RESUME")

        # Per RESUME, cambia nome e traccia resumed_from
        exp_name = request.experiment_name
        resumed_from_name = None
        if result.strategy == "RESUME" and result.parent_run_id:
            parent_exp = find_experiment_by_id(result.parent_run_id)
            if parent_exp:
                resumed_from_name = parent_exp.name
                exp_name = f"derived__{parent_exp.name}"
                logger.info(
                    "RESUME model switch: renaming experiment to '%s', resumed_from='%s'",
                    exp_name, resumed_from_name,
                )

        auto_description = generate_description(
            strategy=result.strategy,
            changed_files=result.changed_files,
            exp_id=result.parent_run_id,
            model_id=request.model_id,
        )
        description = request.description or auto_description

        extra = {**(result.extra or {}), "description": description}
        if resumed_from_name:
            extra["resumed_from"] = resumed_from_name
        result = replace(result, extra=extra)

        experiment = Experiment(
            id=exp_id,
            name=exp_name,
            description=description,
            uri=request.experiment_uri or "",
            run_type=request.run_type,
            base=is_base,
            status=StatusType.RUNNING,
            strategy=StrategyType(result.strategy),
            model_id=request.model_id,
            codebase=json.dumps(snapshot.files) if is_base else json.dumps(result.diff_patch or {}),
            changed_files=result.changed_files or [],
            metrics_uri=None,
            model_uri=request.model_uri or None,
            resumed_from=resumed_from_name,
        )

        if is_base:
            # Per RESUME: promuovi CKP a Model se il modello non esiste nel DB
            if result.strategy == "RESUME" and request.model_id:
                db_model = find_model_by_name(request.model_id)
                if db_model is None and request.model_uri:
                    try:
                        ckp_id = retrieve_ckp_id_by_ckp_uri(request.model_uri)
                        logger.info(
                            "Model %s not found. Promoting CKP %s to temporary Model.",
                            request.model_id, request.model_uri,
                        )
                        promote_checkpoint_to_model(
                            ckp_uri=request.model_uri,
                            model_id=request.model_id,
                            model_uri=request.model_uri,
                            model_name=request.model_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to promote CKP to Model for uri=%s: %s. "
                            "Atomic transaction will fail if Model does not exist.",
                            request.model_uri, e,
                        )

            logger.info(
                "Creating base experiment (atomic): exp_id=%s, name=%s, recipe=%s, component=%s, model=%s, resumed_from=%s",
                exp_id, exp_name, request.recipe_id, request.component_id, request.model_id, resumed_from_name,
            )
            create_base_experiment_node_with_edges(
                exp=experiment,
                recipe_name=request.recipe_id,
                component_name=request.component_id,
                model_name=request.model_id,
                resumed_from=resumed_from_name,
            )
        else:
            edge_type = _STRATEGY_EXP_EDGE_MAP[result.strategy]
            edge_props: dict[str, Any] = {}
            if result.diff_patch:
                edge_props["diff_patch"] = str(result.diff_patch)

            logger.info(
                "Creating experiment with %s edge (atomic): exp_id=%s, parent_run_id=%s",
                edge_type, exp_id, result.parent_run_id,
            )
            create_non_base_experiment_with_chain_edge(
                exp=experiment,
                parent_exp_id=result.parent_run_id,
                strategy=edge_type,
                edge_properties=edge_props or None,
            )

        return exp_id

    def on_post(self, request: PostRequest) -> None:
        """Hook POST-execution.

        REFACTOR: nessuna operazione CKP-specifica. Lo stato e' gia'
        aggiornato dal server endpoint con update_experiment_status.
        """
        logger.debug(
            "POST handler for exp_id=%s, strategy=%s — no-op.",
            request.experiment_id, request.strategy,
        )