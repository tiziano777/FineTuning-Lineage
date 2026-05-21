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
| 1: Infrastructure | IN PROGRESS | `feature/phase1-infrastructure` |
| 2: Config Schema | PENDING | `feature/phase2-config` |
| 3: DiffManager | PENDING | `feature/phase3-diffmanager` |
| 4: Hook/Decorator | PENDING | `feature/phase4-tracker` |
| 5: Integration E2E | PENDING | `feature/phase5-integration` |
| 6: Documentation | PENDING | `feature/phase6-docs` |
| 7: Polish | PENDING | `feature/phase7-polish` |
| 8: Commit/PR | PENDING | `feature/phase8-commit` |
