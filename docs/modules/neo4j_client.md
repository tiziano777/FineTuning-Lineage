# neo4j_client/ Module — Database Driver & Schema

# Neo4j Client Module

Fast, async Neo4j client with automatic schema initialization and verification.

## Quick Usage

### Automatic Initialization (Recommended)

```python
from graph_lineage.neo4j_client.client import Neo4jClient, get_driver

async def main():
    driver = await get_driver()
    client = Neo4jClient(driver=driver, auto_init=True)
    
    # Initialize schema and verify it once, then safe to use
    success = await client.ensure_initialized()
    
    if success:
        print("✓ Schema ready!")
    else:
        print("✗ Schema verification failed")
```

### In FastAPI (Automatic on Startup)

```python
from fastapi import FastAPI
from graph_lineage.neo4j_client.client import Neo4jClient, get_driver

app = FastAPI()

@app.on_event("startup")
async def startup():
    driver = await get_driver()
    client = Neo4jClient(driver=driver, auto_init=True)
    success = await client.ensure_initialized()
    # API ready when this completes
```

## Core Functions

- **`get_driver(reinit=False)`** → AsyncDriver singleton
- **`close_driver()`** → Close and reset driver
- **`initialize_schema(driver, scripts_dir)`** → Load Cypher files (01-schema.cypher, 02-triggers.cypher)
- **`verify_schema(driver)`** → Validate schema integrity
- **`Neo4jClient.ensure_initialized()`** → Idempotent entry point (calls both above)

## Docker Usage

Run schema initialization in a container:

```bash
docker run -e NEO4J_URI=bolt://neo4j:7687 \
           -e NEO4J_USER=neo4j \
           -e NEO4J_PASSWORD=password \
           myapp python -m graph_lineage.neo4j_client
```

## Features

✓ **Async/await support** — Non-blocking initialization  
✓ **Idempotent** — Safe to call `ensure_initialized()` multiple times  
✓ **Graceful errors** — APOC trigger failures don't block schema setup  
✓ **Detailed logging** — Every step logged with [Schema Init] / [Verification] prefix  
✓ **Connection pooling** — Configurable via `NEO4J_POOL_SIZE` env var  

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Username |
| `NEO4J_PASSWORD` | `password` | Password |
| `NEO4J_POOL_SIZE` | `50` | Connection pool size |

## Troubleshooting

See [docs/modules/neo4j_schema_initialization.md](../../docs/modules/neo4j_schema_initialization.md) for:
- Architecture & design patterns
- Error classification and recovery
- Production deployment checklist
- Debugging guide


## Overview

Provides AsyncNeo4jClient abstraction layer, manages driver lifecycle, initializes graph schema (constraints, indexes, triggers), and verifies schema integrity.

**Location:** `graph_lineage/neo4j_client/`

## Public API

```python
from graph_lineage.neo4j_client import (
    get_driver,              # -> AsyncGraphDatabase.driver()
    close_driver,            # Close singleton driver
    AsyncNeo4jClient,        # Async CRUD wrapper
)

# CLI for schema management
python -m graph_lineage.neo4j_client.init_schema      # Initialize schema
python -m graph_lineage.neo4j_client.verify_schema    # Verify schema
```

## Components

### 1. `client.py` — Singleton Driver Management

**Purpose:** Manage Neo4j driver lifecycle (create once, close on shutdown).

**Key Functions:**
```python
def get_driver() -> AsyncGraphDatabase.driver:
    """Get or create singleton Neo4j driver."""
    # Uses env vars: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
    # Default: neo4j://localhost:7687 (from docker-compose)

def close_driver() -> None:
    """Close driver on shutdown."""
```

**Environment Variables:**
```bash
NEO4J_URI=neo4j://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
```

### 2. `neo4j_async.py` — AsyncNeo4jClient Wrapper

**Purpose:** Async CRUD operations on Experiment, Checkpoint, Recipe, Model, Component nodes.

**Key Methods:**
```python
class AsyncNeo4jClient:
    async def create_experiment(exp: Experiment) -> str
        """Create :Experiment node, return exp_id"""
    
    async def get_experiment(exp_id: str) -> Experiment | None
        """Retrieve by UUID"""
    
    async def find_parent_experiment(project_uri: str) -> Experiment | None
        """Find most recent experiment for project"""
    
    async def create_edge(source_id, relation_type, target_id, props) -> None
        """Create relationship with optional properties"""
    
    async def update_experiment_status(exp_id, status) -> None
        """Mark as COMPLETED/FAILED"""
    
    async def create_checkpoint(ckp: Checkpoint) -> str
        """Create :Checkpoint, return ckp_id"""
```

**All functions are `async`:**
- Uses Neo4j AsyncGraphDatabase (Python async driver)
- Compatible with Streamlit via `nest_asyncio` helper
- Reduces latency on remote DB calls

### 3. `01-schema.cypher` — Graph Schema Definition

**Purpose:** Define all nodes, constraints, indexes, relationships.

**Node Types** (5 total):
```cypher
CREATE CONSTRAINT unique_exp_id FOR (e:Experiment) REQUIRE e.exp_id IS UNIQUE;
CREATE CONSTRAINT unique_ckp_id FOR (c:Checkpoint) REQUIRE c.ckp_id IS UNIQUE;
CREATE CONSTRAINT unique_recipe_id FOR (r:Recipe) REQUIRE r.recipe_id IS UNIQUE;
CREATE CONSTRAINT unique_model_name FOR (m:Model) REQUIRE m.model_name IS UNIQUE;
CREATE CONSTRAINT composite_component FOR (co:Component) REQUIRE (co.technique_code, co.framework_code) IS UNIQUE;
```

**Indexes** (3 BTREE for fast lookup):
```cypher
CREATE INDEX idx_exp_config_hash FOR (e:Experiment) ON (e.config_hash);
CREATE INDEX idx_exp_code_hash FOR (e:Experiment) ON (e.code_hash);
CREATE INDEX idx_exp_req_hash FOR (e:Experiment) ON (e.req_hash);
```

**Relations** (7 types):
| Type | From | To | Purpose |
|------|------|----|-|-----------|
| PRODUCED_BY | :Checkpoint | :Experiment | Checkpoint belongs to run |
| DERIVED_FROM | :Experiment | :Experiment | Branch (includes diff_patch) |
| RETRY_FROM | :Experiment | :Experiment | Same config, different seed |
| MERGED_FROM | :Checkpoint | :Checkpoint | Merge N→1 checkpoints |
| USES_MODEL | :Experiment | :Model | Base model reference |
| USES_RECIPE | :Experiment | :Recipe | Dataset config reference |
| USES_TECHNIQUE | :Experiment | :Component | (Framework, Technique) pair |

### 4. `02-triggers.cypher` — APOC Triggers (Auto-Timestamps & Validation)

**Timestamp Automation:**
```cypher
-- Auto-set created_at on node creation
CREATE TRIGGER timestamp_created_at
  ON CREATE OF (n:Experiment|Checkpoint)
  SET n.created_at = datetime()

-- Auto-update updated_at on property change
CREATE TRIGGER timestamp_updated_at
  ON SET n:Experiment|Checkpoint
  SET n.updated_at = datetime()
```

**Orphan Checkpoint Validation:**
```cypher
-- Reject Checkpoint without parent (unless is_merging=true)
CREATE TRIGGER orphan_validation
  ON SET (c:Checkpoint)
  WHERE NOT EXISTS((c)-[:PRODUCED_BY]->()) AND c.is_merging = false
  RAISE ERROR "Checkpoint must have PRODUCED_BY relation"
```

**Requirements:**
- Neo4j 5.x with APOC plugin installed
- `apoc.trigger.enabled=true` in Neo4j config
- Docker Compose handles this automatically

### 5. `init_schema.py` — Schema Initialization CLI

**Purpose:** Create all constraints, indexes, triggers, and seed data.

**Usage:**
```bash
python -m graph_lineage.neo4j_client.init_schema
```

**What it does:**
1. Connect to Neo4j (from env vars)
2. Run all CREATE statements from `01-schema.cypher`
3. Install APOC triggers from `02-triggers.cypher`
4. Seed base data (207 Components, 5 Models)
5. Report status: ✓ Schema initialized

### 6. `verify_schema.py` — Schema Verification CLI

**Purpose:** Check that schema matches ground truth (all constraints, indexes, triggers present).

**Usage:**
```bash
python -m graph_lineage.neo4j_client.verify_schema
```

**Checks:**
1. 5 node types exist ✓
2. 5 UNIQUE constraints enforced ✓
3. 3 BTREE indexes created ✓
4. Seed data loaded (207 Components, 5+ Models) ✓
5. APOC triggers configured ✓
6. No orphan checkpoints (unless `is_merging=true`) ✓

**Output:**
```
✓ Schema verification passed (all 5 checks)
✓ 1487 nodes in graph
✓ 10 Experiment nodes
✓ 25 Checkpoint nodes
✓ No orphan checkpoints detected
```

---

## Data Flow

```
Application Start
       │
       ▼
get_driver()
       │
       ├─ Connect to Neo4j (from env vars or defaults)
       ├─ Test connection (RETURN 1)
       │
       ▼
Driver ready for queries
       │
       ├─ lineage/neo4j_ops.py uses AsyncNeo4jClient
       ├─ Streamlit UI uses AsyncNeo4jClient
       │
       ▼
On shutdown:
  close_driver()
```

## Schema Initialization Workflow

```
First time setup:
  1. docker compose up neo4j -d
  2. python -m graph_lineage.neo4j_client.init_schema
  3. python -m graph_lineage.neo4j_client.verify_schema
  4. (Success) → ready for experiments

Later verifications:
  python -m graph_lineage.neo4j_client.verify_schema
  → detects any schema drift or missing triggers
```

---

## Async Pattern

All CRUD operations are async:

```python
from graph_lineage.neo4j_client import AsyncNeo4jClient

client = AsyncNeo4jClient()

# Must run in async context
async def train():
    exp_id = await client.create_experiment(experiment_node)
    await client.create_edge(exp_id, "USES_MODEL", model_id)
    status = await client.update_experiment_status(exp_id, "completed")

# In sync context (Streamlit), wrap with run_async()
from graph_lineage.streamlit_ui.utils import run_async
exp_id = run_async(train())
```

---

## Testing

**Location:** `tests/test_neo4j_*.py`

**Coverage:**
- Driver connection (mocked)
- Async CRUD operations
- Schema initialization (verify all statements run)
- Schema verification (all checks pass)

**Example:**
```python
@pytest.mark.asyncio
async def test_create_experiment():
    client = AsyncNeo4jClient()
    exp = Experiment(exp_id="e-001", ...)
    result = await client.create_experiment(exp)
    assert result == "e-001"

def test_init_schema_cypher_valid():
    # Parse 01-schema.cypher, verify all statements are valid Cypher
    ...

def test_verify_schema_all_constraints_exist():
    # Run verification, check that all 5 constraints are reported
    ...
```

---

## Troubleshooting

### Q: "ConnectionError: failed to connect to Neo4j"
**A:** Check env vars: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`. Verify Docker container running: `docker compose ps neo4j`.

### Q: "Schema verification failed: Constraint not found"
**A:** Run `init_schema` to create missing constraints. Or manually run `01-schema.cypher` in Neo4j Browser.

### Q: "Orphan Checkpoint validation error"
**A:** Your Checkpoint node is missing a PRODUCED_BY relationship to its parent Experiment. If this is a merged checkpoint, set `is_merging=true` to bypass validation.

### Q: "How do I query the graph directly?"
**A:** Use Neo4j Browser (http://localhost:7474 from docker-compose), or use `AsyncNeo4jClient.run_query(cypher)` method for custom queries.

---

## Integration

### In lineage/neo4j_ops.py
```python
from graph_lineage.neo4j_client import AsyncNeo4jClient

client = AsyncNeo4jClient()
await client.create_experiment(exp_node)
await client.create_edge(exp_id, "DERIVED_FROM", parent_id, {"diff_patch": patch})
```

### In streamlit_ui/db/repository/
```python
from graph_lineage.neo4j_client import AsyncNeo4jClient

class ExperimentRepository:
    async def list_all(self):
        client = AsyncNeo4jClient()
        return await client.run_query("MATCH (e:Experiment) RETURN e")
```

---

## See Also

- [neo4j_schema.md](../neo4j_schema.md) — Detailed schema reference + queries
- [LINEAGE_SYSTEM_ARCHITECTURE.md](../LINEAGE_SYSTEM_ARCHITECTURE.md#section-3-data-model) — Design rationale for nodes/relations
- [docker-compose.yml](../../docker-compose.yml) — Neo4j container config

