# FineTuning-Lineage

Hook-based experiment lineage tracking for LLM fine-tuning.

## What It Does

Add `@envelope.tracker()` to your training function. The system automatically:

1. **PRE-EXECUTION**: Reads `config.yml`, validates config, detects run type (NEW/RETRY/BRANCH/MERGE), creates Neo4j experiment node
2. **TRAINING**: Your code runs normally
3. **POST-EXECUTION**: Captures metrics URIs, creates checkpoint nodes, updates experiment status

```python
from graph_lineage.lineage import envelope

@envelope.tracker()
def train_loop(config_path: str, device: str):
    # Your training code here
    pass
```

## Architecture

```
config.yml → @envelope.tracker() → DiffManager → Neo4j
                │                       │
                ├── PRE: validate        ├── CodeSnapshot (critical files)
                ├── PRE: decide run_type ├── DiffAnalyzer (diff_match_patch)
                ├── PRE: create nodes    └── RuleEngine (NEW/RETRY/BRANCH/MERGE)
                │
                ├── RUN: user training
                │
                └── POST: metrics + checkpoints + status update
```

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

### 4. Decorate your train function

```python
from graph_lineage.lineage import envelope

@envelope.tracker()
def train(config_path: str, device: str):
    # your training code
    pass

train("config.yml", "cuda:0")
```

### 5. View in UI

```bash
docker compose up streamlit -d
# Open http://localhost:8501
```

## Run Types

| Type | Trigger | Neo4j Edge |
|------|---------|------------|
| **NEW** | First run (no prior experiment) | None (root node) |
| **RETRY** | Same config+code, re-run | `RETRY_OF` |
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
| 4 | Neo4j unavailable |
| 5 | Run type conflict |

## Implementation Status

| Phase | Module | Status |
|-------|--------|--------|
| 1 - Infrastructure | `storage/`, `data_classes/neo4j/`, `neo4j_client/` | ✅ Done |
| 2 - Config Schema | `config_file/` (data_classes, validator, writer) | ✅ Done |
| 3 - DiffManager | `diff/` (snapshot, differ, reconstructor, description) + `history/` | ✅ Done |
| 4 - Hook/Tracker | `lineage/` (decorator, Neo4j integration) | 🔜 Next |
| 5-8 | Integration, Docs, Polish, Ship | ⬜ Planned |

## Project Structure

```
graph_lineage/
├── data_classes/neo4j/         # Pydantic entity models (nodes + edges)
│   ├── nodes/                  # Experiment, Model, Recipe, Component, Checkpoint
│   └── edges/                  # DerivedFrom, relations enum
├── neo4j_client/               # Neo4j driver, schema init, verification
├── storage/                    # Storage abstraction (LocalProvider, resolver)
├── config_file/                # Config schema + validation + write-back
│   ├── data_classes/           # Pydantic models per config namespace
│   ├── commit_msg/             # YML message templates + loader
│   ├── validator.py            # Strict pre-execution validation
│   └── writer.py              # Atomic YAML write-back (UUID injection)
├── diff/                       # DiffManager system
│   ├── snapshot.py             # CodebaseSnapshot (4 critical files, frozen)
│   ├── differ.py               # SHA-256 hashing, unified diff generation
│   ├── description.py          # Auto-generated commit messages per strategy
│   └── reconstructor.py        # Codebase reconstruction from lineage chain
├── history/                    # Experiment history tracking
│   ├── models.py               # HistoryEntry Pydantic model
│   └── repository.py           # JSON-based local history repository
├── lineage/                    # Hook/decorator system (Phase 4 - TODO)
└── streamlit_ui/               # CRUD UI for Neo4j entities
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

- [Config Reference](docs/CONFIG.md)
- [Middleware/Hook System](docs/MIDDLEWARE.md)
- [Neo4j Schema](docs/neo4j_schema.md)
- [Architecture](docs/LINEAGE_SYSTEM_ARCHITECTURE.md)
- [Error Handling](docs/ERROR_HANDLING.md)
- [Examples](docs/EXAMPLES.md)
