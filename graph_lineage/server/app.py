"""FastAPI application for the Lineage Server.

Endpoints:
    GET  /health       → Health check (DB connectivity)
    POST /api/v1/pre   → PRE-execution lifecycle (handler dispatch)
    POST /api/v1/post  → POST-execution lifecycle (update status + handler hook)
    POST /api/v1/checkpoint → Mid-training checkpoint creation (wrapper su generic node)
    POST /graph/nodes  → Creazione nodo generico collegato a un run

Run with: uvicorn graph_lineage.server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import sys
import uuid
import json
from fastapi import FastAPI, HTTPException

from graph_lineage.data_classes.neo4j.nodes.experiment import StatusType, StrategyType
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.lineage.generic_node_ops import create_generic_edge, create_generic_graph_node
from graph_lineage.lineage.experiment_neo4j_ops import find_experiment_by_id, update_experiment_status

from graph_lineage.server.handlers.registry import get_handler
from graph_lineage.server.handlers.training import ModelIdMismatchError, ModelDbMismatchError

from .schemas import (
    CheckpointRequest,
    CheckpointResponse,
    GenericNodeRequest,
    GenericNodeResponse,
    HealthResponse,
    PostRequest,
    PostResponse,
    PreRequest,
    PreResponse,
)

# Configura logging base
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
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


# ─────────────────────────────────────────────────────────────────────────
# STARTUP EVENT: Initialize and verify Neo4j schema
# ─────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_initialize_schema():
    """Initialize and verify Neo4j schema on server startup."""
    try:
        from graph_lineage.neo4j_client.client import Neo4jClient, get_driver

        logger.info("[Startup] Initializing Neo4j schema and verification...")

        # Get driver
        driver = await get_driver()

        # Create client and ensure schema is initialized and verified
        client = Neo4jClient(driver=driver, auto_init=True)
        success = await client.ensure_initialized()

        if success:
            logger.info("[Startup] ✓ Neo4j schema initialized and verified successfully")
        else:
            logger.error("[Startup] ✗ Neo4j schema initialization or verification failed")
            logger.error("[Startup] API will continue but may encounter issues")

    except Exception as e:
        logger.error("[Startup] Unexpected error during schema initialization: %s", e)
        logger.error("[Startup] API will continue but may encounter issues")


# ─────────────────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────
# PRE-EXECUTION
# ─────────────────────────────────────────────────────────────────────────
@app.post("/api/v1/pre", response_model=PreResponse)
async def pre_execution(request: PreRequest) -> PreResponse:
    """PRE-execution endpoint: dispatch to run-type handler, detect strategy, create run node.

    Flow:
    1. Build CodebaseSnapshot from request codebase
    2. Look up parent/current experiment (for response resolution)
    3. Dispatch to RunTypeHandler.detect()
    4. Create Experiment node via handler.create_nodes()
    5. Resolve base_experiment_id for response
    6. Return strategy + run_id
    """
    try:
        logger.info("START PRE: %s", str(request.experiment_id))
        logger.info("run_type: %s", request.run_type)

        # 1. Build snapshot from client codebase content
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
        logger.info("snapshot files: %d", len(snapshot.files))

        # 2.a Find parent experiment if exists (by previous_experiment_id)
        parent = None
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

        # 3. Dispatch to handler
        handler = get_handler(request.run_type)
        try:
            result = await handler.detect(request)
        except (ModelIdMismatchError, ModelDbMismatchError) as e:
            raise HTTPException(status_code=409, detail=str(e))

        logger.info(
            "run type detected: strategy=%s, parent_run_id=%s, parent_ckp_id=%s",
            result.strategy, result.parent_run_id, result.parent_ckp_id,
        )

        # 4. Create run node and edges
        run_id = handler.create_nodes(request, result)

        # 5. Resolve base_experiment_id for response
        response_base_exp_id = request.base_experiment_id
        if result.strategy == StrategyType.NEW:
            response_base_exp_id = run_id
        elif not response_base_exp_id and result.strategy != StrategyType.NEW:
            if parent and parent.base:
                response_base_exp_id = parent.id
            elif request.previous_experiment_id:
                response_base_exp_id = request.previous_experiment_id

        logger.info(
            "PRE complete: strategy=%s, run_id=%s, base_exp_id=%s, previous_experiment_id=%s",
            result.strategy, run_id, response_base_exp_id, request.experiment_id,
        )

        return PreResponse(
            experiment_id=run_id,
            strategy=StrategyType(result.strategy),
            base=result.strategy == StrategyType.NEW,
            description=result.extra.get("description", "") if result.extra else "",
            base_experiment_id=response_base_exp_id,
            previous_experiment_id=request.experiment_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PRE-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────
# POST-EXECUTION
# ─────────────────────────────────────────────────────────────────────────
@app.post("/api/v1/post", response_model=PostResponse)
async def post_execution(request: PostRequest) -> PostResponse:
    """POST-execution endpoint: update experiment status, then dispatch handler hook."""
    logger.info("START POST: %s", str(request))
    try:
        # 1. Generic status update
        update_experiment_status(
            exp_id=request.experiment_id,
            status=StatusType(request.status),
            exit_msg=request.exit_message,
            metrics_uri=request.metrics_uri,
        )

        # 2. Dispatch handler-specific post logic
        exp = find_experiment_by_id(request.experiment_id)
        if exp is None:
            raise HTTPException(
                status_code=422,
                detail=f"experiment_id '{request.experiment_id}' not found in DB",
            )

        handler = get_handler(exp.experiment_type)
        handler.on_post(request)

        logger.info(
            "POST complete: exp_id=%s, status=%s",
            request.experiment_id, request.status,
        )

        return PostResponse(
            experiment_id=request.experiment_id,
            status=StatusType(request.status),
            acknowledged=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────
# CHECKPOINT (backward compatibility — wrapper su generic node)
# ─────────────────────────────────────────────────────────────────────────
@app.post("/api/v1/checkpoint", response_model=CheckpointResponse)
async def checkpoint_created(request: CheckpointRequest) -> CheckpointResponse:
    """Checkpoint endpoint: create checkpoint node and link to experiment.

    Implementato come caso specifico dell'endpoint generico /graph/nodes.
    Ora crea nodi con label :Node:Checkpoint per essere trovati da
    MATCH (n:Checkpoint) o MATCH (n:Node {type: "Checkpoint"}).
    """
    try:
        ckp_id = str(uuid.uuid4())

        # Funzioni SYNC (coerenti con neo4j_ops) — NO await
        create_generic_graph_node(
            node_id=ckp_id,
            node_type="Checkpoint",
            payload={
                "name": request.name,
                "derived_from": request.derived_from,
                "epoch": request.epoch,
                "run": request.run,
                "uri": request.uri,
                "metrics": request.metrics,
                "is_merging": request.is_merging,
            },
        )
        create_generic_edge(
            parent_id=request.experiment_id,
            child_id=ckp_id,
            edge_type="PRODUCED",
        )

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


# ─────────────────────────────────────────────────────────────────────────
# GENERIC NODE
# ─────────────────────────────────────────────────────────────────────────
@app.post("/graph/nodes", response_model=GenericNodeResponse)
async def create_generic_node(request: GenericNodeRequest) -> GenericNodeResponse:
    """Crea un nodo generico collegato a un run esistente.

    Endpoint generico per nodi custom (Metric, Artifact, Alert, ...)
    senza necessità di un endpoint dedicato per tipo.
    """
    try:
        node_id = str(uuid.uuid4())

        # Funzioni SYNC (coerenti con neo4j_ops) — NO await
        create_generic_graph_node(
            node_id=node_id,
            node_type=request.node_type,
            payload=request.payload,
        )
        create_generic_edge(
            parent_id=request.run_id,
            child_id=node_id,
            edge_type=request.edge_type,
        )

        logger.info(
            "Generic node created: node_id=%s, type=%s, run_id=%s, edge=%s",
            node_id, request.node_type, request.run_id, request.edge_type,
        )

        return GenericNodeResponse(node_id=node_id, acknowledged=True)

    except Exception as e:
        logger.error("Generic node server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

