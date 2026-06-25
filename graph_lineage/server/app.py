"""FastAPI application for the Lineage Server.

Endpoints:
    GET  /health       → Health check (DB connectivity)
    POST /api/v1/pre   → PRE-execution lifecycle (rule engine + create experiment)
    POST /api/v1/post  → POST-execution lifecycle (update status)
    POST /api/v1/checkpoint → Mid-training checkpoint creation

Run with: uvicorn graph_lineage.server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import sys
import uuid
import json
from typing import Any
from fastapi import FastAPI, HTTPException

from graph_lineage.data_classes.neo4j.nodes.checkpoint import Checkpoint
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.diff.description import generate_description
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.lineage.neo4j_ops import (
    create_checkpoint_edge, create_checkpoint_node,create_experiment_edge,
    create_experiment_node, create_resumed_from_edge, find_experiment_by_id,
    update_experiment_status,create_ckp_derived_from_edge,retrieve_ckp_id_by_ckp_uri,retrieve_ckp_by_experiment_id )
from graph_lineage.lineage.rule_engine import ModelIdMismatchError, detect_run_type

from .schemas import CheckpointRequest, CheckpointResponse, HealthResponse, PostRequest, PostResponse, PreRequest, PreResponse

# Configura logging base
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Silenzia TUTTO Uvicorn
for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Silenzia httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

app = FastAPI(
    title="Lineage Tracking Server",
    version=__version__,
    description="Receives experiment lifecycle events from remote GPU workers.",
)

# Edge type mapping per strategy — Experiment→Experiment edges only.
# RESUME and BRANCH-with-checkpoint also create a separate Experiment→Checkpoint
# RESUMED_FROM edge via create_resumed_from_edge(), handled explicitly below.
_STRATEGY_EXP_EDGE_MAP: dict[str, str] = {
    "BRANCH": "DERIVED_FROM",
    "RETRY": "RETRY_FROM",   # aligned with schema: (Experiment)-[:RETRY_FROM]→(Experiment)
    "MERGE": "MERGED_FROM",
    "RESUME": "RESUMED_FROM"  # aligned with schema: (Experiment)-[:RESUMED_FROM]→(Experiment) (Experiment)-[:CKP_RESUMED_FROM]→(Checkpoint)
}


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    neo4j_ok = False
    try:
        from graph_lineage.neo4j_client.client import get_driver
        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        neo4j_ok = True
    except Exception:
        pass

    return HealthResponse(
        status="ok" if neo4j_ok else "degraded",
        version=__version__,
        neo4j_connected=neo4j_ok,
    )


@app.post("/api/v1/pre", response_model=PreResponse)
async def pre_execution(request: PreRequest) -> PreResponse:
    """PRE-execution endpoint: detect strategy, create experiment node.

    Flow:
    1. Build CodebaseSnapshot from request codebase
    2. Look up parent experiment (by base_experiment_id or URI)
    3. Build minimal LineageConfig for rule_engine
    4. Detect run type
    5. Create Experiment node in Neo4j
    6. Create edges based on strategy:
       - BRANCH  → DERIVED_FROM (Exp→Exp) + optionally RESUMED_FROM (Exp→Ckp)
       - RETRY   → RETRY_FROM (Exp→Exp)
       - RESUME  → RESUMED_FROM (Exp→Ckp) only
       - MERGE   → DERIVED_FROM (Exp→Exp)
    7. Return strategy + experiment_id
    """
    try:
        logger.info("START PRE: %s", str(request.experiment_id))
        # 1. Build snapshot from client codebase content
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
        logger.info("snapshot files: %d", len(snapshot.files))
        
        # 2.a Find parent experiment if exists (by previous_experiment_id)
        
        if request.previous_experiment_id:
            parent = find_experiment_by_id(request.previous_experiment_id)
            if parent is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"previous_experiment_id '{request.previous_experiment_id}' not found in DB",
                )
        else:
            logger.info("no parent experiment found")
        
        # 2.b Find current experiment if exists (by experiment_id)
        if request.experiment_id:
            t_exp = find_experiment_by_id(request.experiment_id)
            if t_exp is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"experiment_id '{request.experiment_id}' not found in DB",
                )
        else:
            logger.info("no current experiment found")
        

        # 3. Build minimal LineageConfig for rule_engine
        from graph_lineage.config_file.data_classes.lineage_config import LineageConfig

        config = LineageConfig.model_validate({
            "experiment": {
                "name": request.experiment_name,
                "uri": request.experiment_uri,
                "id": request.experiment_id,
                "previous_experiment_id": request.previous_experiment_id,
                "base_experiment_id": request.base_experiment_id,   
                "base": request.base,
                "model_id": request.model_id,
                "component_id": request.component_id,
                "recipe_id": request.recipe_id,
            },
            "model": {
                "model_id": request.model_id or "",
                "model_uri": request.model_uri or "",
                "checkpoint_resume_from": request.checkpoint_resume_from,
            },
            "model_merging": {"enabled": request.merging},
        }, strict=False)

        # 4. Detect run type
        # ModelIdMismatchError → HTTP 409 (client maps to exit code 7)
        try:
            run_result = await detect_run_type(config, snapshot)
        except ModelIdMismatchError as e:
            raise HTTPException(status_code=409, detail=str(e))
        #except Exception as e:
        #    raise HTTPException(status_code=400, detail=str(e))


        logger.info(
            "run type detected: strategy=%s, parent_exp_id=%s, parent_ckp_id=%s",
            run_result.strategy, run_result.parent_exp_id, run_result.parent_ckp_id,
        )

        # 5. Build Experiment node
        exp_id = str(uuid.uuid4())
        is_base = run_result.strategy == "NEW"


        auto_description = generate_description(
            strategy=run_result.strategy,
            changed_files=run_result.changed_files,
            exp_id=run_result.parent_exp_id,
            ckp_id=run_result.parent_ckp_id,
        )
        description = request.description or auto_description

        experiment = Experiment(
            id=exp_id,
            description=description,
            uri=request.experiment_uri or "",
            base=is_base,
            status="RUNNING",
            strategy=run_result.strategy,
            model_id=request.model_id,
            codebase= json.dumps(snapshot.files) if is_base else json.dumps(run_result.diff_patch or {}),
            changed_files=run_result.changed_files or [],
            # metrics_uri is populated at POST time (not known at PRE)
            metrics_uri=None,
            model_uri=request.model_uri or None
        )

        # 6. Create node in Neo4j
        create_experiment_node(experiment)

        # 7. Create exp2exp edges based on strategy
        # Experiment→Experiment edges (DERIVED_FROM, RETRY_FROM, RESUMED_FROM) are created here.
        if run_result.parent_exp_id and run_result.strategy in _STRATEGY_EXP_EDGE_MAP:
            edge_type = _STRATEGY_EXP_EDGE_MAP[run_result.strategy]
            edge_props: dict[str, Any] = {}
            if run_result.diff_patch:
                edge_props["diff_patch"] = str(run_result.diff_patch)
            logger.info(
                "Creating %s edge: from=%s, to=%s, props=%s",
                edge_type, run_result.parent_exp_id, exp_id, edge_props,
            )
            create_experiment_edge(to_id=run_result.parent_exp_id, from_id=exp_id, rel_type=edge_type, properties=edge_props or None)

        # Experiment→Checkpoint RESUMED_FROM edge:
        # - RESUME always has parent_ckp_id (the checkpoint to resume from)
        # ONLY IF A CHECKPOINT IS INVOLVED (parent_ckp_id is not None)
        if run_result.strategy =="RESUME":
            logger.info("Creating CKP_RESUMED_FROM edge: exp_id=%s, ckp_uri=%s", exp_id, run_result.parent_ckp_id)
            create_resumed_from_edge(exp_id, run_result.parent_ckp_id)

        # 8. Resolve base_experiment_id for response
        response_base_exp_id = request.base_experiment_id

        if run_result.strategy == "NEW":
            # Per NEW, l'experiment_id è anche il base_experiment_id
            response_base_exp_id = exp_id
        elif not response_base_exp_id and run_result.strategy != "NEW":
            if parent and parent.base:
                response_base_exp_id = parent.id
            elif request.previous_experiment_id:
                response_base_exp_id = request.previous_experiment_id

        logger.info(
            "PRE complete: strategy=%s, exp_id=%s, base_exp_id=%s, previous_experiment_id=%s",
            run_result.strategy, exp_id, response_base_exp_id, request.experiment_id,
        )

        return PreResponse(
            experiment_id=exp_id, # New Experiment ID created 
            strategy=run_result.strategy,
            base=is_base,
            description=description,
            base_experiment_id=response_base_exp_id,
            previous_experiment_id=request.experiment_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PRE-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/post", response_model=PostResponse)
async def post_execution(request: PostRequest) -> PostResponse:
    """POST-execution endpoint: update experiment status."""
    logger.info("START POST: %s", str(request))
    try:
        update_experiment_status(
            exp_id=request.experiment_id,
            status=request.status,
            exit_msg=request.exit_message,
            metrics_uri=request.metrics_uri,
        )
        
        # ckp2ckp edge creation for RESUME strategy after experiment is completed
        if request.status == "COMPLETED" and request.strategy == "RESUME" and request.checkpoint_resume_from:
            old_checkpoint = retrieve_ckp_id_by_ckp_uri(request.checkpoint_resume_from)
            new_ckps = retrieve_ckp_by_experiment_id(request.experiment_id)
            if new_ckps:
                first_ckp = None
                min=0
                for ckp in new_ckps:
                    if min == 0 or ckp.epoch < min:
                        min = ckp.epoch
                        first_ckp = ckp
                
                logger.info(
                    "Creating CKP_DERIVED_FROM edge: base_ckp_id=%s, new_ckp_id=%s",
                    old_checkpoint, first_ckp.id,
                )
                create_ckp_derived_from_edge(base_ckp_id=old_checkpoint, new_ckp_id=first_ckp.id)
            

        logger.info(
            "POST complete: exp_id=%s, status=%s",
            request.experiment_id, request.status,
        )

        return PostResponse(
            experiment_id=request.experiment_id,
            status=request.status,
            acknowledged=True,
        )

    except Exception as e:
        logger.error("POST-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/checkpoint", response_model=CheckpointResponse)
async def checkpoint_created(request: CheckpointRequest) -> CheckpointResponse:
    """Checkpoint endpoint: create checkpoint node and link to experiment.

    Flow:
    1. Build Checkpoint entity from request
    2. Create Checkpoint node in Neo4j
    3. Create (Experiment)-[:PRODUCED]->(Checkpoint) edge
    4. Return checkpoint_id acknowledgement
    """
    try:
        ckp_id = str(uuid.uuid4())

        checkpoint = Checkpoint(
            id=ckp_id,
            name=request.name,
            derived_from=request.derived_from,
            epoch=request.epoch,
            run=request.run,
            uri=request.uri,
            metrics=request.metrics,
            is_merging=request.is_merging,
        )

        create_checkpoint_node(checkpoint)
        create_checkpoint_edge(request.experiment_id, ckp_id)

        logger.info(
            "Checkpoint created: id=%s, name=%s, exp=%s",
            ckp_id, request.name, request.experiment_id,
        )

        return CheckpointResponse(
            checkpoint_id=ckp_id,
            experiment_id=request.experiment_id,
            acknowledged=True,
        )

    except Exception as e:
        logger.error("Checkpoint server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    