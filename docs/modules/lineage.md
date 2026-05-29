# lineage/ Module — Core Tracking Logic

## Overview

The heart of the experiment lineage system. Detects run type strategy based on codebase state, then executes Neo4j mutations (create experiment nodes, edges, checkpoint tracking).

**Location:** `graph_lineage/lineage/`

## Public API

```python
from graph_lineage.lineage import (
    detect_run_type,          # -> RunTypeResult
    neo4j_ops,                # async CRUD operations
)
```

## Components

### 1. `rule_engine.py` — Run Type Detection

**Purpose:** Classify a training run into one of 5 strategies: NEW, RETRY, BRANCH, RESUME, MERGE.

**Key Classes:**
- `RunTypeResult` — Result dataclass with `strategy`, `parent_exp_id`, `parent_ckp_id`, `diff_patch`, `changed_files`
- `ModelIdMismatchError` — Raised if model.model_id changed (blocking error)

**Key Functions:**
- `detect_run_type(config, current_snapshot, parent_experiment) -> RunTypeResult`
- `_looks_like_checkpoint_id(value: str) -> bool` — Detect checkpoint references

**Decision Logic** (in order):
1. If `model_merging.enabled` → MERGE
2. If `checkpoint_resume_from` explicitly set → RESUME
3. If `model_uri` looks like checkpoint path (auto-detect) → RESUME
4. If `previous_experiment_id == id` (explicit signal) → RETRY
5. If no parent experiment → NEW
6. Compare hashes (config, code, requirements):
   - All match → RETRY
   - Any differ → BRANCH

**Blocking Guard:**
- If `model_id` changed from parent → `ModelIdMismatchError` (exit code 7)

### 2. `neo4j_ops.py` — Async Neo4j CRUD

**Purpose:** Execute mutations in Neo4j: create nodes, edges, update status.

**Key Functions:**
- `create_experiment_node(exp: Experiment) -> str` — Create :Experiment node, return exp_id
- `create_edge(source_id, target_id, relation_type, properties) -> None` — Link nodes
- `update_experiment_status(exp_id, status) -> None` — Mark as COMPLETED/FAILED
- `create_checkpoint_node(ckp: Checkpoint) -> str` — Create :Checkpoint node
- `create_checkpoint_edge(exp_id, ckp_id) -> None` — Create (Experiment)-[:PRODUCED]->(Checkpoint)

**Async Driver:**
- Uses `AsyncNeo4jClient` from `neo4j_client/`
- All functions are `async def` (via `nest_asyncio` for Streamlit compat)

### 3. `tracker.py` — PRE/POST Lifecycle (Future)

**Note:** This is documented in README but not yet fully exposed in main package. The Client SDK (`setups/_base/modules/lineage/`) contains the full implementation.

Expected API (when stabilized):
```python
@envelope.tracker()
def train(config_path: str, device: str):
    # PRE: validate config, detect run type, create experiment node
    # TRAIN: your code runs
    # POST: capture metrics URIs, create checkpoints, update status
    pass
```

---

## Data Flow

```
Input:
  ├─ config: LineageConfig (from config.yml + .lineage/experiment.yml)
  ├─ current_snapshot: CodebaseSnapshot (captured files + hashes)
  └─ parent_experiment: Experiment | None (from DB or None if NEW)

Detect Run Type:
  ├─ rule_engine.detect_run_type() → RunTypeResult
  └─ → strategy, parent_exp_id, diff_patch, changed_files

Create Neo4j Mutation:
  ├─ neo4j_ops.create_experiment_node() → new_exp_id
  ├─ If RETRY/BRANCH/MERGE: neo4j_ops.create_edge(parent, relation_type, new_exp)
  ├─ If BRANCH: attach diff_patch to DERIVED_FROM edge
  └─ If POST: neo4j_ops.create_checkpoint_node() + update_experiment_status()

Output:
  └─ Updated .lineage/experiment.yml + Neo4j graph
```

---

## Exit Codes

| Code | Scenario | Fix |
|------|----------|-----|
| 7 | `ModelIdMismatchError` — model_id changed | Restore old model_id or create new setup |
| 8 | `FileTooLargeError` — file > 10MB in snapshot | Remove/compress large files |
| 4 | PRE-execution error (generic) | Check logs, verify config.yml |

---

## Integration

### Local Mode (Future)
```python
from graph_lineage.lineage import tracker

@tracker.envelope.tracker()
def train(...):
    ...
```

### Remote Mode (Current)
```python
from modules.lineage import lineage_tracker  # from Client SDK

@lineage_tracker()
def train(...):
    ...
    # Sends snapshot + config to server → rule_engine + neo4j_ops
```

### Remote Mode with Checkpoint Capture
```python
from modules.lineage import lineage_tracker

@lineage_tracker(capture_checkpoints=True)
def train(config_path: str, lineage_callback=None):
    # lineage_callback is injected by the decorator (LineageCheckpointCallback)
    trainer = Trainer(
        ...,
        callbacks=[lineage_callback]  # sends on_save events to server
    )
    trainer.train()
```

**Flow:**
1. Decorator runs PRE → gets `ExecutionContext`
2. Creates `LineageCheckpointCallback(ctx)` and injects as `lineage_callback` kwarg
3. During training, HuggingFace Trainer calls `on_save()` on each checkpoint save
4. Callback sends `CheckpointRequest` to server → creates Checkpoint node + PRODUCED edge
5. After training, decorator runs POST as normal

### Server Endpoint
```python
POST /api/v1/pre
  Input: codebase snapshot, config
  → lineage/rule_engine.detect_run_type()
  → lineage/neo4j_ops.create_experiment_node()
  Output: exp_id, strategy, changed_files

POST /api/v1/post
  Input: exp_id, status (COMPLETED/FAILED)
  → lineage/neo4j_ops.update_experiment_status()

POST /api/v1/checkpoint
  Input: experiment_id, name, epoch, run, uri, metrics, derived_from, is_merging
  → lineage/neo4j_ops.create_checkpoint_node()
  → lineage/neo4j_ops.create_checkpoint_edge()
  Output: checkpoint_id
```

---

## Testing

**Location:** `tests/test_lineage.py`

**Coverage:**
- Run type detection matrix (NEW, RETRY, BRANCH, RESUME, MERGE)
- Hash matching logic
- ModelIdMismatchError blocking
- Neo4j node/edge creation (mocked driver)

**Example:**
```python
def test_detect_run_type_new():
    result = detect_run_type(config, snapshot, parent=None)
    assert result.strategy == "NEW"

def test_detect_run_type_branch():
    result = detect_run_type(config, new_snapshot, parent=old_exp)
    assert result.strategy == "BRANCH"
    assert result.diff_patch is not None
```

---

## Troubleshooting

### Q: "How do I trace why my run type was detected as X?"
**A:** 1. Check `RunTypeResult.strategy` returned from PRE endpoint. 2. Add logging to `detect_run_type()` to see decision path. 3. Inspect parent experiment in Neo4j UI.

### Q: "ModelIdMismatchError — what does it mean?"
**A:** Your `config.yml` model.model_id differs from the parent experiment's model_id. Either restore the old model_id, or delete `.lineage/experiment.yml` to start a new setup.

### Q: "My file is > 10MB — what can I do?"
**A:** Exclude it from snapshot (add to `.lineage/.gitignore` or scan rules in `diff/snapshot.py`), or compress it. Files > 10MB → `FileTooLargeError` (exit code 8).

---

## See Also

- [diff.md](diff.md) — How codebase snapshots are captured + diffed
- [neo4j_client.md](neo4j_client.md) — AsyncNeo4jClient CRUD details
- [config_file.md](config_file.md) — LineageConfig parsing
- [Rule Engine Internals](../LINEAGE_SYSTEM_ARCHITECTURE.md#section-4-logica-di-branching-e-casistiche) — Design decisions

