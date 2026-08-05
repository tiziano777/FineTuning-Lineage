"""
FastAPI application for the Lineage Server.
"""
from __future__ import annotations

import logging
import sys
from fastapi import FastAPI, HTTPException

from graph_lineage.server.dispatch.domain_dispatcher import DomainDispatcher
from graph_lineage.server.dispatch.registry import HandlerRegistry
from graph_lineage.server.lineage_repository.generic_event_repository import GenericEventRepository

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

    Risolve l'handler dal dominio della request e delega interamente
    a handler.resolve_request(): detection strategia, model constraint
    check/switch, e scrittura sul grafo tramite il repository
    dell'handler. app.py si limita a ritornare lo stato aggiornato.
    """
    try:
        logger.info("START PRE: %s", str(request.experiment_id))
        logger.info("domain: %s", request.user_domain)

        registry = HandlerRegistry()
        handler = DomainDispatcher(registry).resolve_handler(request)
        logger.info("Resolved handler: domain=%s, run_type=%s, handler=%s",
                    getattr(request, "user_domain", "auto-detected"),
                    request.user_domain, handler.__class__.__name__)

        result = await handler.resolve_request(request)

        logger.info(
            "PRE complete: strategy=%s, run_id=%s, base_exp_id=%s, is_base=%s",
            result.strategy, result.run_id, result.base_experiment_id, result.base,
        )

        return PreResponse(
            experiment_id=result.run_id,
            strategy=result.strategy,
            base=result.base,
            description=result.description,
            base_experiment_id=result.base_experiment_id,
            previous_experiment_id=request.experiment_id,
            user_domain=request.user_domain,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PRE-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ── POST-EXECUTION  ───────────────────────────
@app.post("/api/v1/post", response_model=PostResponse)
async def post_execution(request: PostRequest) -> PostResponse:
    """POST-execution endpoint: thin dispatcher.

    Risolve l'handler dal dominio della request e delega interamente
    a handler.resolve_post(): update status, lookup experiment (422 se
    mancante), e hook on_post. app.py si limita a ritornare lo stato.
    """
    logger.info("START POST: %s", str(request))
    try:
        registry = HandlerRegistry()
        handler = DomainDispatcher(registry).resolve_handler(request)

        result = handler.resolve_post(request)

        return PostResponse(
            experiment_id=result.experiment_id,
            status=result.status,
            acknowledged=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST-execution server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ── GENERIC NODE EVENT ──
@app.post("/graph/nodes", response_model=EventNodeResponse)
async def create_event_node(request: EventNodeRequest) -> EventNodeResponse:
    """Crea un nodo generico collegato a un run esistente."""
    try:
        neo4j_params = request.to_neo4j_params()
        node_id = neo4j_params["node_id"]
        node_type = neo4j_params["node_type"]
        payload_json = neo4j_params["payload_json"]

        # No Dispatcher and registry, this is a generic node creation
        # not tied to a specific domain or run_type.
        generic_handler = GenericEventRepository()

        generic_handler.create_generic_graph_node(
            node_id=node_id,
            node_type=node_type,
            payload_json=payload_json,
        )

        generic_handler.create_generic_edge(
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



# ── Checkpoint NODE EVENT ──
# estendi EventnodeRequest to EventCheckpointRequest for checkpoint-specific fields
'''
@app.post("/graph/nodes/checkpoint", response_model=EventNodeResponse)
async def create_event_checkpoint_node(request: EventCheckpointRequest) -> EventNodeResponse:
    """Crea un nodo checkpoint collegato a un run esistente."""
    try:
        neo4j_params = request.to_neo4j_params()
        ckp_id = neo4j_params["ckp_id"]
        node_type = "Checkpoint"
        payload_json = neo4j_params["payload_json"]

        # No Dispatcher and registry, this is a generic node creation
        # extends GenericEventRepository to CheckpointEventRepository
        ckp_handler = CheckpointEventRepository()

        ckp_handler.create_checkpoint_graph_node(
            ckp_id=ckp_id,
            node_type=node_type,
            payload_json=payload_json,
        )

        ckp_handler.create_checkpoint_edge(
            parent_id=neo4j_params["run_id"],
            child_id=ckp_id,
            edge_type=neo4j_params["edge_type"],
        )

        logger.info(
            "Checkpoint node created: ckp_id=%s, type=%s, run_id=%s, edge=%s",
            ckp_id, node_type, neo4j_params["run_id"], neo4j_params["edge_type"],
        )

        return EventNodeResponse(node_id=ckp_id, acknowledged=True)

    except Exception as e:
        logger.error("Checkpoint node server error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
'''