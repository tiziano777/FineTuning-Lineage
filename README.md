# FineTuning-Lineage

Hook-based experiment lineage tracking for LLM fine-tuning.

## What It Does

Add `@envelope.tracker()` to your training function. The system automatically:

1. **PRE-EXECUTION**: Reads `config.yml`, validates config, detects run type (NEW/RETRY/BRANCH/MERGE), creates Neo4j experiment node
2. **TRAINING**: Your code runs normally
3. **POST-EXECUTION**: Captures metrics URIs, creates checkpoint nodes, updates experiment status

### Remote Mode (GPU worker → server via HTTP) — Recommended

```python
from modules.lineage import lineage_tracker

@lineage_tracker()
def train_loop(config_path: str, device: str):
    # Your training code here
    pass
```

Requires `.lineage/server.yml` pointing to the lineage server.

**⚠️ Note:** Local mode (`@envelope.tracker()`) is in development. Use remote mode for production.

See [docs/AUDIT.md](docs/AUDIT.md) for details on current implementation status.

## Architecture

```
LOCAL MODE (same machine):
  .lineage/experiment.yml ─┐
                           ├→ @envelope.tracker() → rule_engine → Neo4j
  config.yml ──────────────┘

REMOTE MODE (GPU worker → server):
  .lineage/experiment.yml ─┐
  .lineage/server.yml      ├→ @lineage_tracker() → HTTP → FastAPI server → Neo4j
  config.yml ──────────────┘
```

### Remote Architecture

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  GPU WORKER                 │   HTTP  │  LINEAGE SERVER             │
│  modules/lineage/           │ ──────► │  graph_lineage/server/      │
│  @lineage_tracker()         │         │  /api/v1/pre + /api/v1/post │
│  capture_codebase()         │         │  rule_engine + Neo4j        │
└─────────────────────────────┘         └─────────────────────────────┘
```

### Split Config Mode

Lineage uses a **split config** approach:
- `.lineage/experiment.yml` — managed by the hook (experiment metadata, IDs, status)
- `config.yml` — user-owned (model, recipe, output, hardware settings)

This keeps lineage concerns separate from training configuration.

## Quick Start

### 1. Start Neo4j

```bash
docker compose up neo4j -d
```

### 2. Install

```bash
pip install -e ".[dev]"
```

### 3. Create config.yml

```yaml
experiment:
  id: null                    # Auto-generated on first run
  derived_from: null
  base_experiment: null
  expected_run_type: "auto"

model:
  - model_name: "llama-7b"
    hyperparameters:
      learning_rate: 0.001
      batch_size: 32

component:
  - framework: "trl"
  - technique: "sft"

recipe:
  id: "your-recipe-uuid"
  name: "my_recipe"
  scope: "sft"
  tasks: []
  entries: {}

output:
  output_dir: /nfs/training-output/.dpo-cache/checkpoints
  metrics_uri: /nfs/training-output/.dpo-cache/metrics

```

### 4. Decorate your train function (Remote Mode)

```python
from modules.lineage import lineage_tracker

@lineage_tracker()
def train(config_path: str, device: str):
    # your training code
    pass

train("config.yml", "cuda:0")
```

⚠️ **First time?** Copy Client SDK into your project:
```bash
cp -r graph_lineage/setups/_base/modules ./
```

### 5. View in UI

```bash
docker compose up streamlit -d
# Open http://localhost:8501
```

## Remote Mode (Lineage Server)

For GPU workers that don't have direct access to Neo4j.

### 1. Start the server

```bash
uvicorn graph_lineage.server.app:app --host 0.0.0.0 --port 8000
```

### 2. Configure the worker

Create `.lineage/server.yml` in your training project:

```yaml
url: "http://lineage-server:8000"
protocol: http
timeout: 30
retries: 3
blocking: true    # if false, training starts even if server is down
```

### 3. Use the Client SDK decorator

```python
from modules.lineage import lineage_tracker

@lineage_tracker()
def train(config_path: str, device: str):
    # your training code
    pass

train("config.yml", "cuda:0")
```

The Client SDK (`modules/lineage/`) is self-contained — copy it from `graph_lineage/setups/_base/modules/lineage/`.

## Run Types

| Type | Trigger | Neo4j Edge |
|------|---------|------------|
| **NEW** | First run (no prior experiment) | None (root node) |
| **RETRY** | Same config+code, re-run | `RETRY_FROM` |
| **BRANCH** | Critical files changed | `DERIVED_FROM` + diff_patch |
| **RESUME** | Resume from checkpoint | `STARTED_FROM` |
| **MERGE** | `model_merging` in config | `MERGED_FROM` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Training crashed |
| 2 | Config validation error |
| 3 | Storage/filesystem error |
| 4 | Neo4j unavailable / PRE-execution error |
| 5 | Run type conflict |
| 6 | `base_experiment_id` not found in DB |
| 7 | `ModelIdMismatchError` — model_id changed between runs |
| 8 | `FileTooLargeError` — file > 10MB in codebase |
| 9 | Server rejected request (4xx) |
| 10 | Server unreachable (blocking mode) |

## Implementation Status

| Phase | Module | Status |
|-------|--------|--------|
| 1 - Infrastructure | `storage/`, `data_classes/neo4j/`, `neo4j_client/` | ✅ Done |
| 2 - Config Schema | `config_file/` (data_classes, validator, writer) | ✅ Done |
| 3 - DiffManager | `diff/` (snapshot, differ, reconstructor, description) + `history/` | ✅ Done |
| 4 - Hook/Tracker | `lineage/` (tracker, rule_engine, neo4j_ops) + `observability/` | ✅ Done |
| 4 - Hook/Tracker | `lineage/` (tracker, rule_engine, neo4j_ops) + `observability/` | ✅ Done |
| 5 - Streamlit UI | `streamlit_ui/` (9 pages, CRUD, graph viz, admin) | ✅ Done |
| 6 - Client-Server | `server/` (FastAPI) + `setups/_base/modules/lineage/` (Client SDK) | ✅ Done |
| 7+ | Deploy, Docs, Polish | ⬜ Planned |

## Setups (Scaffolding Templates)

Pre-built project templates with lineage tracking already wired:

| Setup | Description | Mode |
|-------|-------------|------|
| `graph_lineage/setups/_base/` | Base template (Client SDK + .lineage/ config) | Remote |
| `graph_lineage/setups/sft_trl/` | Supervised Fine-Tuning with TRL | Local |
| `graph_lineage/setups/dpo_trl/` | Direct Preference Optimization with TRL | Local |
| `graph_lineage/setups/continual_ft_trl/` | Continual fine-tuning (resume adapter) | Local |

The `_base/` template includes `modules/lineage/` — a standalone Client SDK that communicates with the lineage server via HTTP (no `pip install graph_lineage` needed on the worker).

Each setup includes `train.py`, `requirements.txt`, and `.lineage/` directory.

## Project Structure

```
graph_lineage/
├── config_file/                # Config schema + validation + write-back
│   ├── data_classes/           # Pydantic models (LineageConfig, TrainingConfig, ExperimentConfig)
│   ├── validator.py            # Strict pre-execution validation
│   └── writer.py              # Atomic YAML write-back (UUID injection)
├── data_classes/neo4j/         # Pydantic entity models
│   └── nodes/                  # Experiment, Model, Recipe, Component, Checkpoint
├── diff/                       # Codebase diff & snapshot
│   ├── snapshot.py             # CodebaseSnapshot (scan rules, FileTooLargeError)
│   ├── differ.py               # compute_snapshot_diff(), detect_changes()
│   ├── description.py          # Auto-generated descriptions per strategy
│   └── reconstructor.py        # Codebase reconstruction from base + diffs
├── history/                    # Experiment history tracking
│   ├── models.py               # Navigation DTOs
│   └── repository.py           # Navigate, rollback, squash
├── lineage/                    # Hook/decorator system (local mode)
│   ├── tracker.py              # @envelope.tracker() — PRE/POST lifecycle
│   ├── rule_engine.py          # detect_run_type(): NEW/RETRY/BRANCH/RESUME/MERGE
│   └── neo4j_ops.py            # Async Neo4j CRUD
├── neo4j_client/               # Database driver + schema
│   ├── client.py               # get_driver() / close_driver()
│   ├── neo4j_async.py          # AsyncNeo4jClient
│   ├── init_schema.py          # Schema initialization CLI
│   └── verify_schema.py        # Schema verification CLI
├── observability/              # Metrics collection
│   ├── collector.py            # MetricsCollector (JSONL + OpenLIT)
│   └── hw.py                   # GPU stats (pynvml)
├── server/                     # FastAPI lineage server (Phase 6)
│   ├── app.py                  # /health, /api/v1/pre, /api/v1/post
│   └── schemas.py              # Server-side Pydantic models
├── setups/                     # Scaffolding templates
│   ├── _base/                  # Base template
│   │   ├── .lineage/           # experiment.yml + server.yml
│   │   └── modules/lineage/    # Client SDK (standalone, no pip install needed)
│   ├── sft_trl/                # SFT with TRL
│   ├── dpo_trl/                # DPO with TRL
│   └── continual_ft_trl/       # Continual fine-tuning
├── storage/                    # Storage abstraction (LocalProvider, resolver)
├── streamlit_ui/               # CRUD UI for Neo4j entities (Streamlit)
└── observability/              # Metrics collection (MetricsCollector, GPU stats)
```

## Development

```bash
# Install dev deps
pip install -e ".[dev]"

# Run tests
pytest -v

# Lint
ruff check .

# Start Neo4j
docker compose up neo4j -d
```

## Docs

- [Audit](docs/AUDIT.md) — Documentation audit (design vs reality)
- [Module Docs](docs/modules/) — Complete reference for each module
- [Workflow](docs/workflow.md) — Development & deployment workflow
- [Neo4j Schema](docs/neo4j_schema.md) — Graph schema reference
- [Architecture](docs/LINEAGE_SYSTEM_ARCHITECTURE.md) — System design overview
