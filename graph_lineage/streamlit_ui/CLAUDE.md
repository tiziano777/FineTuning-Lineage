# CLAUDE.md -- streamlit_ui/

UI subsystem to create and refine with metadata static components as Neo4J nodes:
- Component
- Recipe Loader
- Models
- Experiment-codebase linker (generates a few line to copy to a config.yml file)

So we have Streamlit frontend + Neo4j-backed CRUD layer.
- Lineage and cypher interface to visualize Experiments chains. 

NOTE: wa can also generate experiements and related experiments by the. use of the middleware logics.

## Dependencies and rules

- Python 3.10+ (union syntax `X | Y`)
- Pydantic v2 for all models
- Type hints on public functions
- TDD: pytest + quick iterations
- Think before code. Surface tradeoffs. Ask if unclear.
- Simplicity first. Minimum code. No speculative features.
- Surgical changes. Touch only what's asked. Clean up your own mess.

## UI Architecture

### Structure

```
streamlit_ui/* TO SCAN
```

### Page Pattern

Each `ui_pages/{entities}.py` follows:

```python
# 1. Async helpers (wrap repository calls)
async def create_{entity}_async(...):
    db_client = get_neo4j_client()
    repo = {Entity}Repository(db_client)
    return await repo.create(...)

# 2. Main render function
def run() -> None:
    st.title(...)
    tab1, tab2 = st.tabs(["Upload", "Browse"])
    # Tab 1: Create
    # Tab 2: List + Edit + Delete (via expanders)
```

**Key:** Async helpers isolate DB calls. UI layer stays thin.

### CRUD Layer

**Entity** (Pydantic model):
- Inherits `BaseEntity` (id, created_at, updated_at)
- Validates shape + cross-field logic
- No DB knowledge

**Repository** (Neo4j queries):
- Implements: `create()`, `list_with_limit()`, `search()`, `update()`, `delete()`, `is_deletable()`
- All Cypher scripts in method bodies
- Returns dict for JSON serialization to UI

### Neo4j Schema

Version-controlled at `neo4j/`:
- `01-schema.cypher` — Node types, constraints, indexes (idempotent)
- `02-triggers.cypher` — APOC triggers for timestamps
- `03-seeds.cypher` — Seed data (Components, Models)

Loaded via `ensure_schema_initialized()` in app.py on startup (once per session).

### Error Handling

**Custom exceptions** (utils/errors.py):
- `UIError(user_message, details)` — User-safe message + log details
- `DuplicateRecipeError` — Name collision with recovery UI

**Pattern:**
```python
try:
    # CRUD op
except UIError as e:
    st.error(f"Error: {e.user_message}")
    st.caption(e.details)  # Tech details for logs
```

### Session State

Streamlit session_state for:
- `config` — Loaded from env (Neo4j URI, API URL)
- `api_token` — From MASTER_API_TOKEN env
- `current_page` — Sidebar page selection
- `schema_initialized` — One-time flag for DDL load
- `{entity}_{action}_{key}` — Per-form edit/delete toggles

### Dependencies

- **streamlit** — UI framework
- **pydantic v2** — Data validation
- **neo4j** — Async driver
- **pyyaml** — Recipe YAML parsing

### Testing

- `tests/` — pytest suite
- Import pattern: relative imports within streamlit_ui
- Fixtures in `conftest.py` (mock db_client, async loop)
- Test asyncio ops: use `pytest-asyncio`

## Metadata Fields (Recipe Example)

Root-level YAML metadata flows end-to-end:

```yaml
id: <uuid>
name: my_recipe
description: "..."
scope: sft
tasks: [task1, task2]
tags: [tag1, tag2]
derived_from: <parent-uuid>  # Optional: parent recipe reference
entries:
  entry_object_1: ...
  entry_object_2: ...
```

→ Parsed by RecipeRepository.create_from_yaml() → Entity validation → Neo4j node → UI display

All 5 metadata fields (scope, tasks, tags, derived_from, description) persist. Display in Browse tab under metadata section.

## Key Files to Touch

TO SCAN
