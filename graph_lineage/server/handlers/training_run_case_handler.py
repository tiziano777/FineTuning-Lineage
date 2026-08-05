"""TrainingRunHandler: logica verticale di training (dominio AI).

REFACTOR v3:
- Rimosso checkpoint_resume_from (deprecato).
- RESUME e' ora model-switch: nuovo base experiment, nessun ponte CKP.
- Model constraint check, blocking/non-blocking, e CKP promotion sono TUTTI qui.
- Il server endpoint e' un thin dispatcher: chiama handler.resolve_request() e handler.resolve_post().
- Node creation delegata al repository (TrainingRepository.create_experiment_nodes).
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from fastapi import HTTPException

import json
import logging

from graph_lineage.case_state_provider.state_provider import GitOrExplicitCodebaseProvider
from graph_lineage.data_classes.neo4j.nodes.base.enum.status_type import StatusType
from graph_lineage.data_classes.neo4j.nodes.code.training.enum.experiment_type import ExperimentType
from graph_lineage.data_classes.neo4j.nodes.code.generic.enum.strategy_type import StrategyType
from graph_lineage.diff_util.snapshot import CodebaseSnapshot
from graph_lineage.server.lineage_repository.training_repository import TrainingRepository
from graph_lineage.server.handlers.run_case_handler import PostRunResolution, PreRunResolution
from graph_lineage.server.handlers.run_case_handler import RunCaseHandler, RunTypeResult
from graph_lineage.server.schemas import PostRequest, PreRequest

logger = logging.getLogger(__name__)

class ExperimentConfig(BaseModel):
    """Strict experiment configuration — managed by the lineage hook."""

    id: str | None = None
    previous_experiment_id: str | None = None
    base_experiment_id: str | None = None
    base: bool | None
    name: str = Field(..., min_length=1)
    description: str = ""
    user_domain: ExperimentType = Field(..., description="training | evaluation | inference | merging")
    uri: str | None = None 
    status: str | None = None
    model: str | None = None 
    component: str | None = None
    recipe: str | None = None

class ModelIdMismatchError(Exception):
    """Raised when model constraint is broken and blocking=True."""
    pass

class ModelDbMismatchError(Exception):
    """DEPRECATED: kept for backward-compat server catch."""
    pass

class TrainingRunHandler(RunCaseHandler):
    """Handler per run di tipo training.

    Responsabilita': decidere la strategy (NEW, BRANCH, RETRY, MERGE, RESUME)
    e delegare la creazione dei nodi Experiment al repository.
    Il model switch (RESUME) e' gestito interamente qui.
    - detect_strategy ritorna RunTypeResult (solo detection, nessuna scrittura sul grafo)
    - resolve_request applica la strategy (scrittura sul grafo via repository) e ritorna PreRunResolution
    """

    user_domain = "training"

    def __init__(self):
        super().__init__(state_provider=GitOrExplicitCodebaseProvider())
        self.experiment_handler = TrainingRepository()

    @staticmethod
    async def _reconstruct_full_codebase_from_experiment(self, experiment_id: str) -> CodebaseSnapshot:
        """Ricostruisce la codebase completa per un esperimento risalendo la catena."""
        chain = []
        current_id = experiment_id

        while True:
            exp = self.experiment_handler.find_experiment_by_id(current_id)
            if not exp:
                raise ValueError(f"Experiment {current_id} not found")

            chain.append({"id": exp.id, "codebase": exp.codebase, "base": exp.base})

            if exp.base:
                break

            parent_id = self.experiment_handler.find_parent_experiment_id(current_id)
            if parent_id is None:
                break
            current_id = parent_id

        chain.reverse()
        from graph_lineage.diff_util.reconstructor import reconstruct_codebase
        full_codebase = reconstruct_codebase(chain)
        return CodebaseSnapshot(files=full_codebase)


    async def resolve_request(self, request: PreRequest) -> PreRunResolution:
        """Detect la strategy, applica l'update al grafo tramite il repository, e ritorna lo stato PRE finale."""
        try:
            result = await self.detect_strategy(request)
        except (ModelIdMismatchError, ModelDbMismatchError) as e:
            raise HTTPException(status_code=409, detail=str(e))

        creation = self.experiment_handler.create_experiment_nodes(request, result)
        if not creation.run_id:
            raise ValueError("create_experiment_nodes() returned empty run_id")

        parent = None
        if request.previous_experiment_id:
            parent = self.experiment_handler.find_experiment_by_id(request.previous_experiment_id)

        is_base = result.strategy in (StrategyType.NEW.value, StrategyType.RESUME.value)
        base_experiment_id = request.base_experiment_id
        if is_base:
            base_experiment_id = creation.run_id
        elif not base_experiment_id:
            if parent and parent.base:
                base_experiment_id = parent.id
            elif request.previous_experiment_id:
                base_experiment_id = request.previous_experiment_id

        logger.info(
            "PRE complete: strategy=%s, run_id=%s, base_exp_id=%s, is_base=%s",
            result.strategy, creation.run_id, base_experiment_id, is_base,
        )

        return PreRunResolution(
            run_id=creation.run_id,
            strategy=StrategyType(result.strategy),
            base=is_base,
            description=creation.description,
            base_experiment_id=base_experiment_id,
        )

    async def detect_strategy(self, request: PreRequest) -> RunTypeResult:
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
            experiment_type=request.user_domain,
            user_domain=request.user_domain,
        )

        # 0. NEW: nessun experiment corrente e non e' base
        if not exp.id and not exp.base:
            logger.info("No experiment id and not base — strategy=NEW")
            return RunTypeResult(strategy=StrategyType.NEW)

        # 1. MERGE: merging e' attivo
        if request.merging:
            logger.info("Merging enabled — strategy=MERGE")
            return RunTypeResult(strategy=StrategyType.MERGE)

        # 2. MODEL CONSTRAINT CHECK (gestito interamente nell'handler)
        current_model_uri = request.model_uri.strip() if request.model_uri else ""
        current_model_name = request.model_id.strip() if request.model_id else ""

        parent_experiment = self.experiment_handler.find_experiment_by_id(exp.previous_experiment_id) if exp.previous_experiment_id else None

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
            db_model = self.experiment_handler.find_model_by_name(current_model_name)
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
            return RunTypeResult(strategy=StrategyType.RESUME)

        # 3. BASE experiment: RETRY vs BRANCH
        if exp.base_experiment_id == exp.id:
            base = self.experiment_handler.find_experiment_by_id(exp.base_experiment_id)
            if base is None:
                raise ValueError(f"Base experiment {exp.base_experiment_id} not found")
            previous_codebase_snapshot = CodebaseSnapshot(files=base.codebase)
            return self.detect_branch_or_retry(
                current_snapshot=snapshot,
                parent_snapshot=previous_codebase_snapshot,
                parent_run_id=exp.id,
            )

        # 4. NON-BASE experiment: RETRY vs BRANCH
        parent_snapshot = await self._reconstruct_full_codebase_from_experiment(self,experiment_id=exp.id)
        result = self.detect_branch_or_retry(
            current_snapshot=snapshot,
            parent_snapshot=parent_snapshot,
            parent_run_id=exp.id,
        )
        logger.info("File changes detected: %s", set(result.changed_files or []))
        return result

    def resolve_post(self, request: PostRequest) -> PostRunResolution:
        """Applica l'update POST-execution tramite il repository e ritorna PostRunResolution."""
        status = StatusType(request.status)
        self.experiment_handler.update_experiment_status(
            exp_id=request.experiment_id,
            status=status,
            exit_msg=request.exit_message,
            metrics_uri=request.metrics_uri,
        )

        exp = self.experiment_handler.find_experiment_by_id(request.experiment_id)
        if exp is None:
            raise HTTPException(
                status_code=422,
                detail=f"experiment_id '{request.experiment_id}' not found in DB",
            )

        self.on_post(request)

        logger.info(
            "POST complete: exp_id=%s, status=%s",
            request.experiment_id, request.status,
        )

        return PostRunResolution(experiment_id=request.experiment_id, status=status)

    def on_post(self, request: PostRequest) -> None:
        """Hook POST-execution.

        REFACTOR: nessuna operazione CKP-specifica. Lo stato e' gia'
        aggiornato dal server endpoint con update_experiment_status.
        """
        logger.debug(
            "POST handler for exp_id=%s, strategy=%s — no-op.",
            request.experiment_id, request.strategy,
        )
