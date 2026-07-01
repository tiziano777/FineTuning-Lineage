# Development & Deployment Workflow

## Quick Start

### 1. Setup Local Development

```bash
# Clone + enter repo
git clone <repo> FineTuning-Lineage
cd FineTuning-Lineage

# Create + activate venv
python3.10 -m venv .venv
source .venv/bin/activate

# Install dev deps
pip install -e ".[dev]"

# Start full stack (Neo4j + schema-init + API + Streamlit)
docker compose up -d

# Wait for services to be healthy
docker compose logs schema-init  # Should show ✓ Schema initialization complete!
docker compose logs api | grep "\[Startup\]"  # Should show ✓ verification passed
```

**✓ Schema is now automatically initialized and verified!**

#### Verify Setup

```bash
# Check all containers
docker compose ps

# Test Neo4j connection
curl http://localhost:7474

# Test API
curl http://localhost:8502/health

# Access Streamlit UI
open http://localhost:8501
```

### 2. Run Tests

```bash
# All tests
pytest -v

# Specific module
pytest tests/test_lineage.py -v

# With coverage
pytest --cov=graph_lineage --cov-report=html
```

### 3. Lint & Format

```bash
# Check style
ruff check .

# Auto-format (if configured)
black graph_lineage tests
```

### 4. Start Development Server

```bash
# FastAPI lineage server (for remote mode testing)
uvicorn graph_lineage.server.app:app --reload --host 127.0.0.1 --port 8000

# Streamlit UI (in separate terminal)
streamlit run graph_lineage/streamlit_ui/app.py
# Opens http://localhost:8501
```

---

## Development Workflow

### Adding a New Module

1. **Create module directory** under `graph_lineage/new_module/`
2. **Add public API** in `__init__.py`
3. **Write implementation** in focused files (1 responsibility per file)
4. **Add tests** in `tests/test_new_module*.py`
5. **Create docs** in `docs/modules/new_module.md`
6. **Update docs/modules/README.md** (add to table + dependency graph)

**Example: New run type strategy**
```bash
# 1. Modify
graph_lineage/lineage/rule_engine.py  # Add detection logic
tests/test_lineage.py                  # Add test case

# 2. Test
pytest tests/test_lineage.py -v

# 3. Document
# Update docs/modules/lineage.md with new strategy
```

### Modifying Existing Module

1. **Read module doc** (docs/modules/module_name.md)
2. **Run existing tests** to verify baseline
3. **Make change** (follow existing patterns)
4. **Add/update test** for new behavior
5. **Update module doc** if API changed
6. **Run full test suite** to catch side effects

### Creating New Neo4j Node Type

1. **Define Pydantic model** in `data_classes/neo4j/nodes/`
2. **Add Cypher constraints** in `neo4j_client/01-schema.cypher`
3. **Create repository** in `streamlit_ui/db/repository/`
4. **Add CRUD tests** in `tests/test_neo4j_*.py`
5. **Create UI page** in `streamlit_ui/ui_pages/` (if needed)
6. **Document** in `docs/modules/data_classes.md`

---

## Testing Strategy

### Test Pyramid

```
        /\
       /E2E\         Integration tests (full system)
      /----\
     /Unit \        Unit tests (isolated modules)
    /------\
```

**Unit tests** (majority):
- Mock Neo4j client
- Test rule engine logic
- Validate config parsing
- Fast (~1 sec for 100+ tests)

**Integration tests** (fewer):
- Real Neo4j in Docker
- Test full PRE/POST flows
- Slower (~10 sec per test)

**E2E tests** (optional):
- Full training simulation
- Rare (only for major milestones)

### Running Tests by Category

```bash
# Unit tests only
pytest -m "not integration" -v

# Integration tests only
pytest -m integration -v

# All tests
pytest -v

# Single file
pytest tests/test_lineage.py -v

# Match pattern
pytest tests/ -k "test_detect_run_type" -v
```

---

## CI/CD Pipeline (Future)

**On every PR:**
```bash
1. Install deps (pip install -e .[dev])
2. Lint (ruff check .)
3. Type check (mypy or pyright, if configured)
4. Unit tests (pytest -m "not integration")
5. Format check (black --check)
```

**On merge to main:**
```bash
1. All tests (pytest -v)
2. Build Docker image
3. Push to registry
4. (Optional) Deploy to staging
```

---

## Deployment

### Local Development (docker-compose)

```bash
docker compose up -d  # Starts neo4j + streamlit (if configured)
docker compose logs -f neo4j  # View logs
docker compose down  # Stop all
```

### Remote Mode (GPU Worker → Server)

**Server side:**
```bash
# Start lineage server
uvicorn graph_lineage.server.app:app --host 0.0.0.0 --port 8000 &

# Or in Docker
docker run -p 8000:8000 -e NEO4J_URI=neo4j://... lineage-server:latest
```

**Worker side:**
```bash
# Copy Client SDK to project
cp -r graph_lineage/setups/_base/modules ./

# Create .lineage/server.yml
cat > .lineage/server.yml << EOF
url: "http://lineage-server:8000"
protocol: http
timeout: 30
retries: 3
blocking: true
EOF

# Run training
python train.py config.yml cuda:0
```

---

## Troubleshooting

### Neo4j Connection Failed
```bash
# Check container
docker compose ps neo4j

# Check logs
docker compose logs neo4j

# Verify connection string
echo $NEO4J_URI  # Should be neo4j://localhost:7687

# Restart
docker compose restart neo4j
```

### Schema Verification Failed
```bash
# Re-initialize schema
python -m graph_lineage.neo4j_client.init_schema

# Verify again
python -m graph_lineage.neo4j_client.verify_schema
```

### Tests Fail with "Neo4j not available"
```bash
# Make sure container is running
docker compose up neo4j -d

# Run tests with explicit Neo4j URI
NEO4J_URI=neo4j://localhost:7687 pytest -v
```

### Streamlit Page Not Loading
```bash
# Clear cache
rm -rf ~/.streamlit

# Restart streamlit
streamlit run graph_lineage/streamlit_ui/app.py --logger.level=debug
```

---

## Documentation Updates

**When to update docs:**
- After adding/removing module
- After changing public API
- After fixing major bug (update example)
- After major refactor

**Which files to update:**
- `docs/modules/module_name.md` — Module-specific docs
- `docs/modules/README.md` — Module index (if new module)
- `README.md` — Quick start, examples, project structure
- `LINEAGE_SYSTEM_ARCHITECTURE.md` — Design decisions (rarely changes)
- `AUDIT.md` — After major incongruence is fixed

**Example workflow:**
```bash
1. Add new feature
2. Run tests (all pass)
3. Update code docstrings
4. Update relevant docs/modules/*.md
5. Update README.md if user-facing
6. Commit with message: "feat: add X, update docs"
```

---

## Common Tasks

### Debug Rule Engine Decision
```python
from graph_lineage.lineage.rule_engine import detect_run_type
from graph_lineage.diff import CodebaseSnapshot
from graph_lineage.config_file.data_classes import LineageConfig

# Load data
config = LineageConfig.from_files("config.yml")
snapshot = CodebaseSnapshot.capture(project_root)
parent = ...  # fetch from DB

# Inspect
result = detect_run_type(config, snapshot, parent)
print(f"Strategy: {result.strategy}")
print(f"Parent: {result.parent_exp_id}")
print(f"Changed files: {result.changed_files}")
```

### Query Neo4j Directly
```bash
# Open Neo4j Browser
open http://localhost:7474

# Or use CLI
cypher-shell -u neo4j -p password
> MATCH (e:Experiment) RETURN e LIMIT 10;
```

### Inspect Config Parsing
```python
from graph_lineage.config_file.data_classes import LineageConfig

config = LineageConfig.from_files("config.yml")
print(config.dict(indent=2))  # Pretty-print all fields
```

### Manually Test Server Endpoint
```bash
curl -X POST http://localhost:8000/api/v1/pre \
  -H "Content-Type: application/json" \
  -d '{
    "codebase": {"train.py": "print(1)"},
    "config": {"model": {"model_name": "llama-7b"}}
  }'
```

---

## Release Checklist

Before tagging a release:

- [ ] All tests pass (`pytest -v`)
- [ ] Linting passes (`ruff check .`)
- [ ] No TODOs in code (or tracked in issues)
- [ ] Docs updated (README, module docs, AUDIT)
- [ ] CHANGELOG.md updated
- [ ] Version bumped in `setup.py` or `pyproject.toml`
- [ ] Commit + push + create GitHub release

---

## See Also

- [README.md](../README.md) — Quick start guide
- [AUDIT.md](../AUDIT.md) — Documentation audit
- [docs/modules/](../modules/) — Module-specific documentation
- [docker-compose.yml](../../docker-compose.yml) — Container configuration

