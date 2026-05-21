# Phase 5: Streamlit UI Redesign - Research

**Researched:** 2026-05-12
**Domain:** Streamlit UI / Neo4j CRUD / async patterns / graph visualization
**Confidence:** HIGH

## Summary

Phase 5 redesigns the Streamlit UI across three tiers: (1) fix asyncio antipatterns and harden existing CRUD for Model/Recipe/Component/Experiment, (2) add graph visualization via streamlit-agraph and expose history operations (rollback/squash/navigate), (3) add an admin console with integrity checks.

The codebase currently uses `asyncio.run()` in every UI page call (12+ occurrences across 4 page files), which creates a new event loop each time. The `AsyncNeo4jClient` already works around this by creating per-call drivers. The fix is `nest_asyncio` + a `run_async()` helper. The history module (`graph_lineage/history/repository.py`) provides complete rollback/squash/navigate/set_visibility operations that just need UI wrappers. Two separate `ExperimentRepository` classes exist (UI CRUD vs history ops) that need bridging.

**Primary recommendation:** Start with the `run_async` helper (US-1), then harden entity CRUD pages (US-2 through US-6), then layer visualization and history UI on top.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Health Check page removed from nav (was never implemented)
- `streamlit-agraph` chosen for graph visualization (US-7)
- UI and DB run on separate servers -- no config.yml access from UI
- Hook client sends dataclass objects, not files
- Soft-delete via `usable`/`is_usable` flag on Experiment + Checkpoint
- Experiment creation is read-only from UI (only hook creates)
- Checkpoint creation is read-only from UI (only hook creates)

### Approved User Stories
- **Tier 1 (P0):** US-1 through US-6 (asyncio fix, Model/Recipe/Component CRUD, Experiment read-only+edit+soft-delete, Checkpoint browse+URI edit+soft-delete)
- **Tier 2 (P1):** US-7 through US-10 (graph viz, history nav, rollback wizard, squash wizard)
- **Tier 3 (P2):** US-11 (admin console with consistency checks)

### Deferred Ideas (OUT OF SCOPE)
None listed in CONTEXT.md.
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | 1.56.0 | UI framework | Already installed and used [VERIFIED: venv import] |
| neo4j (async driver) | installed | Async Neo4j access | Already used via AsyncNeo4jClient [VERIFIED: codebase] |
| nest_asyncio | latest | Fix asyncio.run() in existing loop | Standard Streamlit async fix [ASSUMED] |
| streamlit-agraph | latest | Graph DAG visualization | Locked decision from CONTEXT.md |
| pydantic v2 | installed | Data models | Already used throughout [VERIFIED: codebase] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pyyaml | installed | Recipe YAML parsing | Already used in recipe upload [VERIFIED: codebase] |

**Installation:**
```bash
pip install nest-asyncio streamlit-agraph
```

**Note:** `nest_asyncio` and `streamlit-agraph` are NOT currently installed. [VERIFIED: ModuleNotFoundError in venv]

## Architecture Patterns

### Current Project Structure (relevant)
```
graph_lineage/streamlit_ui/
  app.py                          # Main entry, sidebar nav
  config.py                       # UI config from env
  ui_pages/
    recipes.py, models.py         # CRUD pages (existing)
    experiments.py                 # CRUD page (needs overhaul)
    components.py                  # CRUD page (needs hardening)
  db/
    neo4j_async.py                # AsyncNeo4jClient (per-call drivers)
    repository/
      recipe_repository.py        # Full CRUD
      model_repository.py         # Full CRUD
      experiment_repository.py    # Basic CRUD (missing relationship queries)
      component_repository.py     # Full CRUD
  utils/
    errors.py                     # UIError
    __init__.py                   # get_neo4j_client, get_config, get_api_client

graph_lineage/history/
  repository.py                   # ExperimentRepository (navigate, rollback, squash, set_visibility)
  models.py                       # ExperimentSummary, CheckpointSummary, RollbackPreview, NavigationResult
```

### Pattern 1: run_async Helper (US-1)
**What:** Replace all `asyncio.run()` calls with a single helper that uses `nest_asyncio`
**When to use:** Every async call from Streamlit UI pages
**Example:**
```python
# Source: common Streamlit async pattern [ASSUMED]
import asyncio
import nest_asyncio

nest_asyncio.apply()

def run_async(coro):
    """Run async coroutine safely from Streamlit sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
```

### Pattern 2: Entity Page Structure (existing pattern)
**What:** Each page module has async helpers + `run()` function with tabs
**When to use:** All entity pages follow this identical pattern [VERIFIED: codebase]

### Pattern 3: Two ExperimentRepository Classes
**What:** `streamlit_ui/db/repository/experiment_repository.py` handles basic CRUD. `history/repository.py` handles rollback/squash/navigate. Both accept the same Neo4jClient protocol.
**When to use:** UI pages need to use BOTH. The history repo can be instantiated with the same `get_neo4j_client()`. [VERIFIED: codebase]

### Pattern 4: MERGE (Upsert) for Model by name
**What:** Neo4j MERGE on `model_name` unique constraint for upsert
**Example:**
```cypher
MERGE (m:Model {model_name: $model_name})
ON CREATE SET m.id = $id, m.version = $version, m.uri = $uri,
              m.url = $url, m.doc_url = $doc_url,
              m.description = $description,
              m.created_at = $created_at, m.updated_at = $updated_at
ON MATCH SET m.version = $version, m.uri = $uri, m.url = $url,
             m.doc_url = $doc_url, m.description = $description,
             m.updated_at = $updated_at
RETURN m.id as id, m.model_name as model_name, ...
```
Source: Neo4j MERGE semantics [VERIFIED: `unique_model_name` constraint in neo4j_schema.md]

### Pattern 5: streamlit-agraph DAG
**What:** Render graph nodes/edges using streamlit-agraph
**Example:**
```python
# Source: streamlit-agraph API [ASSUMED]
from streamlit_agraph import agraph, Node, Edge, Config

nodes = [Node(id=exp_id, label=exp_id, size=25, color="#4CAF50") for ...]
edges = [Edge(source=child_id, target=parent_id, label="DERIVED_FROM") for ...]
config = Config(directed=True, hierarchical=True, physics=False)
agraph(nodes=nodes, edges=edges, config=config)
```

### Anti-Patterns to Avoid
- **asyncio.run() in pages:** Creates new event loop each time, breaks when Streamlit already has one running. Use `run_async()` helper instead.
- **Free-text model_id input for experiments:** Current create form asks for model_id as text. Since experiments are read-only from UI, remove the create tab entirely.
- **Separate driver per query:** `AsyncNeo4jClient` creates/closes a driver per call. This is a workaround for the event loop issue. After `nest_asyncio`, consider reverting to a persistent driver (but NOT required for this phase).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async in Streamlit | Custom event loop management | `nest_asyncio.apply()` + helper | Edge cases with nested loops |
| Graph visualization | Custom HTML/JS graph | `streamlit-agraph` | Handles layout, interaction, zoom |
| Rollback logic | New rollback implementation | `history/repository.py` methods | Already implemented and tested |
| Squash logic | New squash implementation | `history/repository.py.squash_chain()` | Already implemented with linearity checks |
| Visibility toggle | Custom usable flag logic | `history/repository.py.set_visibility()` | Handles ancestor chain restoration |

## Common Pitfalls

### Pitfall 1: Two ExperimentRepository Classes
**What goes wrong:** Importing the wrong one, or duplicating logic
**Why it happens:** `streamlit_ui/db/repository/experiment_repository.py` and `history/repository.py` both have `ExperimentRepository`
**How to avoid:** Import history repo with an alias: `from graph_lineage.history.repository import ExperimentRepository as HistoryRepository`. Use UI repo for basic CRUD, history repo for rollback/squash/navigate/visibility.
**Warning signs:** Duplicate method names, conflicting imports

### Pitfall 2: Experiment/Checkpoint Read-Only Constraint
**What goes wrong:** Building create/delete forms for Experiment/Checkpoint
**Why it happens:** Existing code has create/delete tabs for experiments
**How to avoid:** Per CONTEXT.md, only hook creates experiments and checkpoints. UI should show browse + limited edit (description/notes) + soft-delete toggle. Remove create tab, replace delete with soft-delete.
**Warning signs:** Any `CREATE (e:Experiment ...)` query in UI code

### Pitfall 3: is_deletable Direction Mismatch
**What goes wrong:** The existing `ExperimentRepository.is_deletable()` checks OUTGOING relationships (e.g., `(e)-[:PRODUCED]->(cp)`), but per the Neo4j schema, PRODUCED_BY goes FROM checkpoint TO experiment (i.e., `(cp)-[:PRODUCED_BY]->(e)`).
**Why it happens:** Schema uses PRODUCED_BY (ckp->exp) but repository queries PRODUCED (exp->ckp). Need to verify which direction is actually in use.
**How to avoid:** Check the actual Cypher in the schema files and ensure queries match.
**Warning signs:** is_deletable always returning true when it shouldn't

### Pitfall 4: Streamlit Key Collisions
**What goes wrong:** Widget key collisions when adding new pages/tabs
**Why it happens:** Streamlit requires unique `key` params for widgets with same type
**How to avoid:** Namespace all keys: `key=f"exp_browse_{exp_id}"`, `key=f"ckp_edit_{ckp_id}"`

### Pitfall 5: Missing Checkpoint Page
**What goes wrong:** No checkpoint browsing/editing exists at all
**Why it happens:** Never built -- checkpoint CRUD was not in original UI scope
**How to avoid:** Build from scratch following the existing page pattern. Need new `ui_pages/checkpoints.py` and potentially extend experiment_repository or create checkpoint_repository.

## Code Examples

### Existing Repository Interface (verified from codebase)
All UI repositories follow this interface:
```python
class XRepository:
    def __init__(self, db_client: AsyncNeo4jClient): ...
    async def create(self, ...) -> dict: ...
    async def get_by_id(self, id: str) -> Optional[dict]: ...
    async def list_all(self, ...) -> list[dict]: ...
    async def update(self, id: str, ...) -> dict: ...
    async def delete(self, id: str) -> None: ...
    async def is_deletable(self, id: str) -> bool: ...
    async def count_dependencies(self, id: str) -> int: ...
```
[VERIFIED: model_repository.py, experiment_repository.py]

### History Repository API (verified from codebase)
```python
class ExperimentRepository:  # history/repository.py
    async def reconstruct_at(self, target_exp_id: str) -> dict[str, str]
    async def preview_rollback(self, exp_id: str) -> RollbackPreview
    async def apply_rollback(self, preview: RollbackPreview, force: bool = False) -> None
    async def squash_chain(self, from_exp_id: str, to_exp_id: str) -> None
    async def navigate_back(self, exp_id: str, steps: int = 1) -> NavigationResult
    async def navigate_forward(self, exp_id: str, steps: int = 1) -> NavigationResult
    async def set_visibility(self, exp_id: str, usable: bool) -> list[str]
```
[VERIFIED: history/repository.py]

### Experiment Rich Browse Query (needed for US-5)
```cypher
-- Fetch experiment with all relationships for browse view
MATCH (e:Experiment)
OPTIONAL MATCH (e)-[:USES_MODEL]->(m:Model)
OPTIONAL MATCH (e)-[:USES_RECIPE]->(r:Recipe)
OPTIONAL MATCH (e)-[:USES_TECHNIQUE]->(c:Component)
OPTIONAL MATCH (ckp:Checkpoint)-[:PRODUCED_BY]->(e)
WITH e, m, r, c, COUNT(ckp) as ckp_count
RETURN e.exp_id, e.status, e.description, e.usable, e.config_hash,
       e.created_at, m.model_name, r.name as recipe_name,
       c.technique_code, c.framework_code, ckp_count
ORDER BY e.created_at DESC
LIMIT 100
```
Source: Derived from neo4j_schema.md relationships [VERIFIED: schema doc]

### Checkpoint Browse Query (needed for US-6)
```cypher
MATCH (c:Checkpoint)-[:PRODUCED_BY]->(e:Experiment)
OPTIONAL MATCH (e2:Experiment)-[:STARTED_FROM]->(c)
WITH c, e, COLLECT(e2.exp_id) as used_by_exps
RETURN c.ckp_id, c.epoch, c.run, c.metrics_snapshot, c.uri,
       c.is_usable, c.created_at, e.exp_id as parent_exp,
       used_by_exps
ORDER BY c.created_at DESC
LIMIT 100
```
Source: Derived from neo4j_schema.md [VERIFIED: schema doc]

### Integrity Check Queries (US-11)
```cypher
-- 1. Experiments without USES_MODEL
MATCH (e:Experiment) WHERE NOT EXISTS((e)-[:USES_MODEL]->()) RETURN e.exp_id

-- 2. Experiments without USES_RECIPE
MATCH (e:Experiment) WHERE NOT EXISTS((e)-[:USES_RECIPE]->()) RETURN e.exp_id

-- 3. RUNNING for > threshold
MATCH (e:Experiment {status: 'RUNNING'})
WHERE e.created_at < datetime() - duration('PT24H')
RETURN e.exp_id, e.created_at

-- 4. Duplicate config_hash without RETRY_OF
MATCH (e1:Experiment), (e2:Experiment)
WHERE e1.config_hash = e2.config_hash AND e1.exp_id < e2.exp_id
AND NOT EXISTS((e2)-[:RETRY_FROM]->(e1))
AND NOT EXISTS((e1)-[:RETRY_FROM]->(e2))
RETURN e1.exp_id, e2.exp_id, e1.config_hash

-- 5. Cycle detection
MATCH path = (e:Experiment)-[:DERIVED_FROM|RETRY_FROM*]->(e)
RETURN COUNT(path) as cycles
```
Source: CONTEXT.md US-5 integrity checks + neo4j_schema.md [VERIFIED: both docs]

## Config Dataclasses (Phase 2 - for Admin Console)

The `LineageConfig` model validates:
- `experiment`: ExperimentConfig (id, derived_from, base_experiment, expected_run_type)
- `model`: dict with required `model_name` and `framework` keys
- `recipe`: RecipeConfig (id, name, scope, tasks, entries, derived_from)
- `output`: OutputConfig (output_dir, metrics_URI)
- `model_merging`: ModelMergingConfig

[VERIFIED: lineage_config.py]

These dataclasses define which fields the admin console can validate against DB state (e.g., model_name exists in DB, recipe.id exists in DB).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | nest_asyncio.apply() + loop.run_until_complete is the correct pattern for Streamlit async | Architecture Patterns | Medium -- may need alternative async approach |
| A2 | streamlit-agraph supports hierarchical/DAG layout with directed edges | Architecture Patterns | Low -- could fall back to physics-based layout |
| A3 | PRODUCED_BY direction in actual DB matches schema doc (ckp->exp) | Common Pitfalls | High -- existing queries may use wrong direction |

## Open Questions (RESOLVED)

1. **Relationship direction PRODUCED vs PRODUCED_BY** (RESOLVED)
   - What we know: Schema doc says `PRODUCED_BY: Checkpoint -> Experiment`. Existing UI ExperimentRepository queries `(e)-[:PRODUCED]->(cp)`. History repo queries `(e)-[:PRODUCED]->(c:Checkpoint)`.
   - What's unclear: Which direction is actually used in the database? The schema says PRODUCED_BY (ckp->exp) but code uses PRODUCED (exp->ckp).
   - **Resolution:** Plan 03 uses `PRODUCED_BY` (ckp->exp) per schema doc. The code's `PRODUCED` usage is a legacy inconsistency that will be corrected.

2. **Checkpoint repository existence** (RESOLVED)
   - What we know: No `checkpoint_repository.py` exists in `db/repository/`. Checkpoints are queried only via experiment relationships.
   - What's unclear: Should we create a dedicated CheckpointRepository or add checkpoint methods to ExperimentRepository?
   - **Resolution:** Plan 03 creates a dedicated `CheckpointRepository` following the existing repository pattern for consistency.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| streamlit | UI framework | Yes | 1.56.0 | -- |
| neo4j (Python driver) | DB access | Yes | installed | -- |
| nest_asyncio | US-1 async fix | No | -- | pip install required |
| streamlit-agraph | US-7 graph viz | No | -- | pip install required |
| Neo4j server | All DB ops | External (Docker) | -- | Must be running |

**Missing dependencies with no fallback:**
- None blocking (install via pip)

**Missing dependencies with fallback:**
- nest_asyncio and streamlit-agraph: install in Wave 0

## Sources

### Primary (HIGH confidence)
- Codebase scan: all ui_pages/*.py, db/repository/*.py, history/repository.py, history/models.py
- docs/neo4j_schema.md -- full schema reference
- 05-CONTEXT.md -- all user decisions and US designs

### Secondary (MEDIUM confidence)
- Streamlit 1.56.0 runtime behavior with asyncio [VERIFIED: installed version]

### Tertiary (LOW confidence)
- streamlit-agraph API (Node, Edge, Config) -- based on training data, not verified against current version

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified installed packages and codebase patterns
- Architecture: HIGH - all existing patterns verified from source
- Pitfalls: HIGH - identified from reading actual code
- Graph visualization: MEDIUM - streamlit-agraph API from training data

**Research date:** 2026-05-12
**Valid until:** 2026-06-12
