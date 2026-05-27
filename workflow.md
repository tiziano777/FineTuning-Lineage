# Development Workflow

## Setup

```bash
# Clone + venv
git clone <repo-url> && cd FineTuning-Lineage
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Start Neo4j
docker compose up neo4j -d
```

## Daily Dev Cycle

1. **Plan**: Check `.planning/ROADMAP.md` for current phase
2. **Branch**: `git checkout -b feature/<phase-name>`
3. **Test first**: Write test → implement → verify
4. **Commit**: Atomic commits per task group
5. **PR**: One PR per phase

## Testing

```bash
# Unit tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=graph_lineage --cov-report=term-missing

# Single file
pytest tests/test_storage.py -v

# Integration (requires Neo4j running)
pytest tests/integration/ -v -m integration
```

## Linting

```bash
ruff check graph_lineage/ tests/
ruff format graph_lineage/ tests/
```

## Neo4j

```bash
# Start
docker compose up neo4j -d

# Browser: http://localhost:7474 (neo4j / envelope_dev)

# Schema init (auto on Streamlit startup, or manual):
python -m graph_lineage.neo4j_client.init_schema

# Verify schema
python -m graph_lineage.neo4j_client.verify_schema
```

## Streamlit UI

```bash
# Local
streamlit run graph_lineage/streamlit_ui/app.py

# Docker
docker compose up streamlit -d
# http://localhost:8501
```

## Project Phases (v1.0)

| Phase | Status | Branch |
|-------|--------|--------|
| 1: Infrastructure | ✅ DONE | `main` |
| 2: Config Schema | ✅ DONE | `main` |
| 3: DiffManager | ✅ DONE | `main` |
| 4: Hook/Decorator | ✅ DONE | `main` |
| 5: Streamlit UI | ✅ DONE | `main` |
| 6: Client-Server Architecture | ✅ DONE | `main` |
| 7: Documentation | ⬜ NEXT | — |
| 8: Polish | ⬜ PENDING | — |
| 9: Commit/PR | ⬜ PENDING | — |

### Phase 6 Sub-phases

| Sub-phase | Description | Tests |
|-----------|-------------|-------|
| 6.1: Core Refactor | Removed hash fields from Experiment, rewrote snapshot.py (full codebase scan), refactored rule_engine (dict comparison), rewrote description.py (auto-generate), removed commit_msg/ | 172 |
| 6.2: Client SDK | `_base/modules/lineage/` — LineageClient, @lineage_tracker decorator, ServerConfig, models, snapshot capture | +34 |
| 6.3: HTTP Connector | `http_connector.py` (httpx-based), ConnectorFactory with auto-registration | +11 |
| 6.4: FastAPI Server | `graph_lineage/server/` — /health, /api/v1/pre, /api/v1/post endpoints | +12 |
| 6.5: E2E Integration | Full client↔server lifecycle tests (NEW, BRANCH, RETRY, FAILED, decorator) | +5 |

## Config Mode

The project supports **split config mode**:
- `.lineage/experiment.yml` — lineage hook-managed metadata (experiment ID, status, references)
- `.lineage/server.yml` — server connection config (url, protocol, timeout, retries, blocking)
- `config.yml` — user-owned training config (model, recipe, output, hardware)

Use `graph_lineage/setups/` templates to scaffold new projects with the correct structure.

## Server (Lineage API)

```bash
# Start the lineage server
uvicorn graph_lineage.server.app:app --host 0.0.0.0 --port 8000

# Health check
curl http://localhost:8000/health
```

The server receives PRE/POST lifecycle events from remote GPU workers running the Client SDK (`_base/modules/lineage/`). It handles rule engine detection, Neo4j writes, and returns experiment strategy/ID.
