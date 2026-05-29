# server/ Module — FastAPI Lineage Server

## Overview

HTTP server for remote mode. Receives codebase + config from GPU workers, runs rule engine, persists to Neo4j.

**Location:** `graph_lineage/server/`

## Public API

**Endpoints:**

| Path | Method | Purpose |
|------|--------|---------|
| `/health` | GET | Health check + Neo4j connection status |
| `/api/v1/pre` | POST | PRE-execution: detect run type, create experiment |
| `/api/v1/post` | POST | POST-execution: update status |
| `/api/v1/checkpoint` | POST | Checkpoint creation: create node + link to experiment |

## Components

### app.py — FastAPI Application

```python
@app.get("/health")
async def health() -> dict:
    """Return server + Neo4j status."""
    return {
        "status": "ok",
        "neo4j": "connected" | "disconnected",
        "uptime_seconds": ...
    }

@app.post("/api/v1/pre")
async def pre_execution(request: PreRequest) -> PreResponse:
    """
    Input:  CodebaseSnapshot + config
    Output: exp_id, strategy, changed_files
    """
    snapshot = CodebaseSnapshot(**request.codebase)
    config = LineageConfig(**request.config)
    
    parent = await find_parent_experiment(config.experiment.project_uri)
    result = detect_run_type(config, snapshot, parent)
    
    exp_id = await create_experiment_node(...)
    if parent:
        await create_edge(parent.id, result.strategy, exp_id, {...})
    
    return PreResponse(
        exp_id=exp_id,
        strategy=result.strategy,
        changed_files=result.changed_files
    )

@app.post("/api/v1/post")
async def post_execution(request: PostRequest) -> PostResponse:
    """
    Input:  exp_id, status
    Output: confirmation
    """
    await update_experiment_status(request.exp_id, request.status)
    return PostResponse(success=True)

@app.post("/api/v1/checkpoint")
async def checkpoint_created(request: CheckpointRequest) -> CheckpointResponse:
    """
    Input:  experiment_id, name, epoch, run, uri, metrics, derived_from, is_merging
    Output: checkpoint_id acknowledgement
    """
    ckp_id = str(uuid.uuid4())
    checkpoint = Checkpoint(id=ckp_id, name=request.name, ...)
    create_checkpoint_node(checkpoint)
    create_checkpoint_edge(request.experiment_id, ckp_id)
    return CheckpointResponse(checkpoint_id=ckp_id, experiment_id=request.experiment_id)
```

### schemas.py — Pydantic Models

```python
class PreRequest(BaseModel):
    experiment_name: str
    experiment_uri: str | None = None
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None
    description: str | None = None
    model_uri: str = ""
    model_id: str = ""
    codebase: dict[str, str] = Field(default_factory=dict)
    checkpoint_resume_from: str | None = None

class PreResponse(BaseModel):
    experiment_id: str
    strategy: str
    base: bool
    description: str
    base_experiment_id: str | None = None
    previous_experiment_id: str | None = None
    changed_files: list[str] = Field(default_factory=list)

class PostRequest(BaseModel):
    experiment_id: str
    status: str
    exit_message: str | None = None
    metrics_uri: str | None = None

class PostResponse(BaseModel):
    experiment_id: str
    status: str
    acknowledged: bool = True

class CheckpointRequest(BaseModel):
    experiment_id: str
    name: str
    epoch: int
    run: int
    uri: str
    metrics: dict = Field(default_factory=dict)
    derived_from: str = ""
    is_merging: bool = False

class CheckpointResponse(BaseModel):
    checkpoint_id: str
    experiment_id: str
    acknowledged: bool = True
```

---

## Deployment

**Local development:**
```bash
uvicorn graph_lineage.server.app:app --reload --host 127.0.0.1 --port 8000
```

**Production (Docker):**
```dockerfile
FROM python:3.10
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["uvicorn", "graph_lineage.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Docker Compose:**
```yaml
services:
  lineage-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      NEO4J_URI: neo4j://neo4j:7687
      NEO4J_USERNAME: neo4j
      NEO4J_PASSWORD: password
    depends_on:
      - neo4j
```

---

## Integration

**In Client SDK (setups/_base/modules/lineage/):**
```python
# Client captures snapshot + config
snapshot = capture_snapshot(project_root)
config = load_config(config_path)

# Send PRE request
response = await http_client.post(
    f"{server_url}/api/v1/pre",
    json={
        "codebase": snapshot.files,
        "config": config.dict()
    }
)

exp_id = response["exp_id"]
# ... training runs ...

# Send POST request
await http_client.post(
    f"{server_url}/api/v1/post",
    json={
        "exp_id": exp_id,
        "status": "completed",
        "metrics_uri": "/nfs/metrics/e-001.jsonl"
    }
)
```

---

## Testing

Location: `tests/test_server.py`, `tests/test_checkpoint_communication.py`

**Coverage:**
- Endpoint responses (200 OK, 4xx errors)
- PRE logic (run type detection, node creation)
- POST logic (status updates)
- Checkpoint endpoint (node creation, PRODUCED edge, error handling)
- LineageCheckpointCallback (on_save, blocking/non-blocking, run counter)
- Decorator injection (capture_checkpoints=True injects callback)

---

## Error Handling

| HTTP Code | Scenario | Response |
|-----------|----------|----------|
| 200 | Success | PreResponse or PostResponse |
| 400 | Invalid request (bad JSON, missing fields) | `{"error": "...""}` |
| 404 | Parent experiment not found | Exit code 6 |
| 409 | Conflict (model_id mismatch) | Exit code 7 |
| 413 | File too large (> 10MB) | Exit code 8 |
| 500 | Neo4j connection lost | Exit code 4 |

---

## See Also

- [lineage.md](lineage.md) — Rule engine invoked by /api/v1/pre
- [config_file.md](config_file.md) — Config parsing
- [CLIENT SDK Reference](../LINEAGE_SYSTEM_ARCHITECTURE.md#section-7-client-server-architecture) — Client-side implementation

