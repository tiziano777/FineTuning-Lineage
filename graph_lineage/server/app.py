"""
FastAPI application for the Lineage Server.
"""

from __future__ import annotations

import logging
import sys
import json
from fastapi import FastAPI, HTTPException

from graph_lineage.data_classes.neo4j.nodes.base.enum.status_type import StatusType
from graph_lineage.data_classes.neo4j.nodes.code.enum.strategy_type import StrategyType
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.lineage.generic_node_ops import create_generic_edge, create_generic_graph_node
from graph_lineage.lineage.experiment_neo4j_ops import (
    find_experiment_by_id,
    update_experiment_status,
)

from graph_lineage.server.dispatch.registry import resolve_handler, get_handler
from graph_lineage.server.handlers.training_run_handler import ModelIdMismatchError, ModelDbMismatchError

from .schemas import (
    HealthResponse,
    PostRequest, PostResponse,
    PreRequest, PreResponse,
    EventNodeRequest, EventNodeResponse
)

from graph_lineage.neo4j_client.client import PersistentNeo4jClient

# Configura logging base
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

app = FastAPI(
    title="Lineage Tracking Server",
    version=__version__,
    description="Receives experiment lifecycle events from remote GPU workers.",
)

client = PersistentNeo4jClient(auto_init=True).get_instance()

# ── STARTUP ───────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_initialize_schema():
    try:
        success = await client.ensure_initialized()
        if success:
            logger.info("[Startup] ✓ Neo4j schema initialized")
        else:
            logger.error("[Startup] ✗ Neo4j schema init failed")
    except Exception as e:
        logger.error("[Startup] Error: %s", e)

# ── HEALTH ────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    neo4j_ok = False
    try:
        driver = await client.get_driver()
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

# ── PRE-EXECUTION ────────────────────────────
@app.post("/api/v1/pre", response_model=PreResponse)
async def pre_execution(request: PreRequest) -> PreResponse:
    """PRE-execution endpoint: thin dispatcher.

    Delega detect() e create_nodes() all'handler risolto.
    Il model constraint check e il model switch sono gestiti internamente
    dal TrainingRunHandler.
    """
    try:
        logger.info("START PRE: %s", str(request.experiment_id))
        logger.info("run_type: %s", request.run_type)

        # 1. Build snapshot
        snapshot = CodebaseSnapshot(files=json.loads(request.codebase))
        logger.info("snapshot files: %d", len(snapshot.files))

        # 2. Resolve domain handler
        handler = resolve_handler(request)
        logger.info("Resolved handler: domain=%s, run_type=%s, handler=%s",
                    getattr(request, "domain", "auto-detected"),
                    request.run_type,
                    handler.__class__.__name__)

        # 3. Detect strategy (include model constraint check + model switch)
        try:
            result = await handler.detect(request)
        except (ModelIdMismatchError, ModelDbMismatchError) as e:
            raise HTTPException(status_code=409, detail=str(e))

        logger.info(
            "run type detected: strategy=%s, parent_run_id=%s",
            result.strategy, result.parent_run_id,
        )

        # 4. Create run node and edges
        run_id = handler.create_nodes(request, result)
        if not run_id:
            raise HTTPException(status_code=500, detail="handler.create_nodes() returned empty run_id")

        # 5. Resolve base_experiment_id for response
        parent = None
        if request.previous_experiment_id:
            parent = find_experiment_by_id(request.previous_experiment_id)

        response_base_exp_id = request.base_experiment_id
        if result.strategy in (StrategyType.NEW.value, StrategyType.RESUME.value):
            response_base_exp_id = run_id
        elif not response_base_exp_id:
            if parent and parent.base:
                response_base_exp_id = parent.id
            elif request.previous_experiment_id:
                response_base_exp_id = request.previous_experiment_id

        is_base = result.strategy in (StrategyType.NEW.value, StrategyType.RESUME.value)

        logger.info(
            "PRE complete: strategy=%s, run_id=%s, base_exp_id=%s, is_base=%s",
            result.strategy, run_id, response_base_exp_id, is_base,
        )

        return PreResponse(
            experiment_id=run_id,
            strategy=StrategyType(result.strategy),
            base=is_base,
            description=result.extra.get("description", "") if result.extra else "",
            base_experiment_id=response_base_exp_id,
            previous_experiment_id=request.experiment_id,
            resumed_from=result.extra.get("resumed_from") if result.extra else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PRE-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ── POST-EXECUTION  ───────────────────────────
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

        try:
            handler = resolve_handler(exp)
        except Exception:
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

# ── GENERIC NODE ──
@app.post("/graph/nodes", response_model=EventNodeResponse)
async def create_event_node(request: EventNodeRequest) -> EventNodeResponse:
    """Crea un nodo generico collegato a un run esistente."""
    try:
        neo4j_params = request.to_neo4j_params()
        node_id = neo4j_params["node_id"]
        node_type = neo4j_params["node_type"]
        payload_json = neo4j_params["payload_json"]

        create_generic_graph_node(
            node_id=node_id,
            node_type=node_type,
            payload_json=payload_json,
        )

        create_generic_edge(
            parent_id=neo4j_params["run_id"],
            child_id=node_id,
            edge_type=neo4j_params["edge_type"],
        )

        logger.info(
            "Generic node created: node_id=%s, type=%s, run_id=%s, edge=%s",
            node_id, node_type, neo4j_params["run_id"], neo4j_params["edge_type"],
        )

        return EventNodeResponse(node_id=node_id, acknowledged=True)

    except Exception as e:
        logger.error("Generic node server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))