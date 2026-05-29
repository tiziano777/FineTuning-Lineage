# Module Documentation Index

Complete reference for FineTuning-Lineage modules. Each module handles a specific concern in the experiment lineage tracking system.

## Core Modules

| Module | Purpose | Key Classes/Functions | Status |
|--------|---------|----------------------|--------|
| [**config_file**](config_file.md) | Configuration parsing & validation | `LineageConfig`, `ExperimentConfig`, `TrainingConfig` | ✅ Stable |
| [**data_classes**](data_classes.md) | Neo4j entity models | `Experiment`, `Checkpoint`, `Recipe`, `Model`, `Component` | ✅ Stable |
| [**diff**](diff.md) | Codebase diffing & snapshots | `CodebaseSnapshot`, `compute_snapshot_diff()`, `reconstruct_codebase()` | ✅ Stable |
| [**history**](history.md) | Experiment history navigation | `ExperimentRepository`, `navigate()`, `rollback()`, `squash()` | ✅ Stable |
| [**lineage**](lineage.md) | Core tracking logic | `detect_run_type()`, Neo4j ops (CRUD) | ✅ Stable |
| [**neo4j_client**](neo4j_client.md) | Database driver & schema | `AsyncNeo4jClient`, schema init/verify CLI | ✅ Stable |
| [**observability**](observability.md) | Metrics collection | `MetricsCollector`, GPU stats | ⚠️ Optional |
| [**server**](server.md) | FastAPI lineage server | `/api/v1/pre`, `/api/v1/post`, `/health` | ✅ Stable |
| [**storage**](storage.md) | Storage provider abstraction | `StorageProvider` ABC, `StorageResolver` | ✅ Stable |
| [**streamlit_ui**](streamlit_ui.md) | Web UI for Neo4j interaction | 9 pages (recipes, models, experiments, etc.) | ✅ Stable |

---

## Module Dependency Graph

```
┌─────────────────────────────────────────────┐
│  USER CODE (training script)                │
└────────────────┬────────────────────────────┘
                 │
        ┌────────▼────────┐
        │  setups/_base/   │  (Client SDK)
        │  modules/lineage │
        └────────┬─────────┘
                 │
    HTTP/AsyncIO │ (if remote)
                 │
        ┌────────▼────────────────────┐
        │  server/ (FastAPI)          │
        │  /api/v1/pre, /api/v1/post  │
        └────────┬────────────────────┘
                 │
        ┌────────▼────────────────────┐
        │  lineage/                   │
        │  rule_engine + neo4j_ops    │
        └────────┬────────────────────┘
                 │
    ┌────────────┼────────────────────┐
    │            │                    │
    ▼            ▼                    ▼
config_file   diff/             neo4j_client/
    │         snapshot              │
    │         differ          ┌─────▼──────┐
    │         │               │  Neo4j DB  │
    │         ├──────────┐    │            │
    │                   ▼    │            │
    │        data_classes/   │            │
    │        (nodes)         │            │
    └──────────┬─────────────┴────────────┘
               │
        ┌──────▼──────┐
        │ observability│ (optional)
        │ hw / metrics │
        └─────────────┘
```

---

## Quick Start: Finding What You Need

**"I want to understand how experiments are detected"**
→ Read [lineage.md](lineage.md) + `rule_engine.py` docstrings

**"I need to add a new Neo4j node type"**
→ Read [data_classes.md](data_classes.md) + schema definitions

**"How does config validation work?"**
→ Read [config_file.md](config_file.md)

**"I'm building a custom storage backend"**
→ Read [storage.md](storage.md) + `StorageProvider` ABC

**"I want to extend the UI"**
→ Read [streamlit_ui.md](streamlit_ui.md) + add page in `ui_pages/`

**"How do I trace a codebase change?"**
→ Read [diff.md](diff.md) + `CodebaseSnapshot` + `compute_snapshot_diff()`

---

## Architecture Principles

### 1. **Modularity**
Each module is self-contained:
- Has a clear public API in `__init__.py`
- Minimal cross-module imports
- Can be tested in isolation

### 2. **Async-First** (where I/O bound)
- `neo4j_client/` uses AsyncNeo4jClient
- `streamlit_ui/` uses `run_async()` helpers
- Server endpoints are async

### 3. **Type Safety**
- All modules use Pydantic v2 for data models
- Type hints on all public functions
- Strict validation at boundaries

### 4. **Separation of Concerns**
```
config_file/    → Parse & validate user input
data_classes/   → Define entities
diff/           → Detect changes
lineage/        → Decide run type + mutations
neo4j_client/   → Persist to DB
server/         → HTTP exposure
streamlit_ui/   → User interaction
```

---

## Testing Strategy

Each module has corresponding tests in `tests/`:

| Module | Test File | Coverage |
|--------|-----------|----------|
| config_file | tests/test_config_*.py | Config parsing, validation |
| data_classes | tests/test_models.py | Pydantic model validation |
| diff | tests/test_diff_*.py | Snapshot capture, diffing |
| history | tests/test_history.py | Navigation, rollback |
| lineage | tests/test_lineage.py | Run type detection |
| neo4j_client | tests/test_neo4j_*.py | Schema init, async ops |
| observability | tests/test_observability.py | Metrics collection |
| server | tests/test_server.py | FastAPI endpoints |
| storage | tests/test_storage.py | Provider abstraction |
| streamlit_ui | N/A (manual testing) | UI flows (streamlit runs locally) |

---

## Development Workflow

1. **Read** relevant module doc
2. **Grep** codebase for key classes/functions
3. **Run tests** for that module: `pytest tests/test_<module>*.py -v`
4. **Make change** following existing patterns
5. **Add test** for new behavior
6. **Update module doc** if API changed

---

## Integration Points

### Local Mode (same machine as DB)
```
@envelope.tracker() (future)
    ↓
lineage/tracker.py (PRE/POST lifecycle)
    ↓
lineage/rule_engine.py + neo4j_ops.py
    ↓
neo4j_client → Neo4j DB
```

### Remote Mode (GPU worker → Server)
```
@lineage_tracker() (setups/_base/modules/lineage/)
    ↓
HTTP → server/app.py (/api/v1/pre, /api/v1/post)
    ↓
lineage/rule_engine.py + neo4j_ops.py
    ↓
neo4j_client → Neo4j DB
```

### UI Mode (interact with DB)
```
streamlit_ui/app.py (Streamlit multi-page)
    ↓
ui_pages/*.py (Recipes, Models, Experiments, etc.)
    ↓
db/repository/*.py (Async repository pattern)
    ↓
neo4j_client → Neo4j DB
```

---

## Common Tasks

### Add a new run type strategy
1. Update `lineage/rule_engine.py` `detect_run_type()` logic
2. Add exit code in README (if error case)
3. Add test in `tests/test_lineage.py`

### Add a new config field
1. Define in `config_file/data_classes/*.py` (Pydantic model)
2. Add validation in `config_file/__init__.py` if needed
3. Update `docs/CONFIG.md` reference

### Add a new Neo4j entity
1. Create node class in `data_classes/neo4j/nodes/`
2. Add schema in `neo4j_client/01-schema.cypher`
3. Add repository in `streamlit_ui/db/repository/`

### Add a new UI page
1. Create file in `streamlit_ui/ui_pages/page_name.py`
2. Define `run()` function
3. Register in `streamlit_ui/app.py` sidebar navigation

---

## Glossary

| Term | Definition |
|------|-----------|
| **Experiment** | Single training run instance (node in Neo4j) |
| **Checkpoint** | Saved model weights + metrics (node in Neo4j) |
| **Recipe** | Dataset configuration + distribution metadata (node in Neo4j) |
| **Component** | (Technique, Framework) pair—e.g., (DPO, TRL) |
| **Run Type** | Strategy for how to handle a new training run: NEW, RETRY, BRANCH, RESUME, MERGE |
| **CodebaseSnapshot** | Captured state of all files (with hashes) at a point in time |
| **Diff Patch** | JSON-serialized unified diff (for Git-style change representation) |
| **Split Config** | Separation of `.lineage/experiment.yml` (system-managed) and `config.yml` (user-owned) |

---

## See Also

- [AUDIT.md](../AUDIT.md) — Documentation audit (design vs reality)
- [neo4j_schema.md](../neo4j_schema.md) — Neo4j graph schema reference
- [LINEAGE_SYSTEM_ARCHITECTURE.md](../LINEAGE_SYSTEM_ARCHITECTURE.md) — System design overview
- [README.md](../../README.md) — Quick start & overview

