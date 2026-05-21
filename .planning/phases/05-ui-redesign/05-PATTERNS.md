# Phase 5: Streamlit UI Redesign - Pattern Map

**Mapped:** 2026-05-12
**Files analyzed:** 13
**Analogs found:** 11 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `streamlit_ui/utils/async_helpers.py` | utility | request-response | `streamlit_ui/utils/__init__.py` | role-match |
| `streamlit_ui/app.py` | config | request-response | self (modify) | exact |
| `streamlit_ui/ui_pages/models.py` | component | CRUD | self (modify) | exact |
| `streamlit_ui/db/repository/model_repository.py` | repository | CRUD | self (modify) | exact |
| `streamlit_ui/ui_pages/recipes.py` | component | CRUD | self (modify) | exact |
| `streamlit_ui/db/repository/recipe_repository.py` | repository | CRUD | self (modify) | exact |
| `streamlit_ui/ui_pages/components.py` | component | CRUD | `ui_pages/models.py` | exact |
| `streamlit_ui/ui_pages/experiments.py` | component | CRUD | self (modify) | exact |
| `streamlit_ui/db/repository/experiment_repository.py` | repository | CRUD | self (modify) | exact |
| `streamlit_ui/ui_pages/checkpoints.py` | component | CRUD | `ui_pages/models.py` | exact |
| `streamlit_ui/db/repository/checkpoint_repository.py` | repository | CRUD | `db/repository/model_repository.py` | exact |
| `streamlit_ui/ui_pages/graph_viz.py` | component | request-response | none | -- |
| `streamlit_ui/ui_pages/admin.py` | component | request-response | `ui_pages/experiments.py` | role-match |

## Pattern Assignments

### `streamlit_ui/utils/async_helpers.py` (utility, NEW)

**Analog:** `streamlit_ui/utils/__init__.py` (for placement/import conventions)

**Purpose:** Replace all `asyncio.run()` calls across every page file with a single `run_async()` helper.

**Imports pattern** (from RESEARCH.md, no existing analog):
```python
from __future__ import annotations

import asyncio
import nest_asyncio

nest_asyncio.apply()
```

**Core pattern:**
```python
def run_async(coro):
    """Run async coroutine safely from Streamlit sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
```

**Apply to:** Every `asyncio.run(...)` call in `app.py`, `models.py`, `recipes.py`, `experiments.py`, `components.py`, and all new page files. Replace with `run_async(...)`.

---

### `streamlit_ui/ui_pages/models.py` (component, MODIFY -- US-2 upsert)

**Analog:** self

**Imports pattern** (lines 1-13):
```python
from __future__ import annotations

import asyncio
import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.model_repository import ModelRepository
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client

logger = logging.getLogger(__name__)
```

**Async helper pattern** (lines 18-30):
```python
async def create_model_async(
    model_name: str, version: str, url: str, doc_url: str, description: str
) -> dict:
    """Create model asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.create_model(
        model_name=model_name, version=version, url=url,
        doc_url=doc_url, description=description,
    )
```

**Tab structure pattern** (line 76):
```python
tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["Create", "Browse", "Edit", "Delete"])
```

**Error handling pattern** (lines 92-111):
```python
try:
    result = asyncio.run(create_model_async(...))
    st.success(f"Model '{result['model_name']}' created successfully!")
    st.toast("Model created!", icon="...")
except UIError as e:
    st.error(f"Error: {e.user_message}")
except asyncio.TimeoutError:
    st.error("Request timed out. Please try again.")
    logger.exception("Timeout in create_model")
except Exception as e:
    st.error(f"Unexpected error: {str(e)}")
    logger.exception("Uncaught exception in create_model")
```

**Browse container pattern** (lines 119-126):
```python
for model in models:
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{model.get('model_name', 'N/A')}**")
            st.caption(f"Version: {model.get('version', 'N/A')}")
        with col2:
            st.caption(f"Created: {model.get('created_at', 'N/A')}")
```

**Delete with dependency check pattern** (lines 182-205):
```python
is_deletable = asyncio.run(repo.is_deletable(model_id))
if not is_deletable:
    st.warning("This model cannot be deleted because: ...")
else:
    st.success("No dependencies found. Safe to delete.")
    confirm = st.checkbox(f"I confirm deletion of model '{selected_name}'")
    if confirm and st.button("Delete Model"):
        asyncio.run(delete_model_async(model_id))
        st.success("Model deleted!")
```

**Modification for US-2:** Add upsert async helper calling a new `upsert_by_name()` repository method. Add "Upsert" tab or integrate into Create tab with MERGE semantics.

---

### `streamlit_ui/db/repository/model_repository.py` (repository, MODIFY -- US-2 upsert)

**Analog:** self

**Repository class pattern** (lines 16-22):
```python
class ModelRepository:
    def __init__(self, db_client: AsyncNeo4jClient):
        self.db = db_client
        self.constraints = EntityConstraints(db_client)
```

**Create with Cypher pattern** (lines 48-83):
```python
now = datetime.utcnow().isoformat()
query = """
CREATE (m:Model {
    id: $id, model_name: $model_name, version: $version,
    ...
    created_at: $created_at, updated_at: $updated_at
})
RETURN m.id as id, m.model_name as model_name, ...
"""
result = await self.db.run_single(query, id=model_id, ...)
if not result:
    raise UIError("Failed to create model in Neo4j")
```

**Modification for US-2:** Add `upsert_by_name()` using MERGE Cypher (from RESEARCH.md):
```cypher
MERGE (m:Model {model_name: $model_name})
ON CREATE SET m.id = $id, m.version = $version, ...
ON MATCH SET m.version = $version, ...
RETURN m.id as id, m.model_name as model_name, ...
```

---

### `streamlit_ui/ui_pages/experiments.py` (component, MAJOR REWRITE -- US-5)

**Analog:** `ui_pages/models.py` (for browse/edit patterns), self (for experiment-specific logic)

**Key changes per CONTEXT.md US-5:**
- Remove Create tab (experiments are read-only from UI)
- Remove Delete tab (replace with soft-delete toggle)
- Add rich browse with relationships (USES_MODEL, USES_RECIPE, USES_TECHNIQUE, checkpoint count)
- Add "HIDDEN" badge for usable=false
- Edit only: description, manual notes
- Add soft-delete/restore toggle using `history/repository.py:set_visibility()`

**New import needed:**
```python
from graph_lineage.history.repository import ExperimentRepository as HistoryRepository
```

**New tab structure:**
```python
tab_browse, tab_edit, tab_visibility = st.tabs(["Browse", "Edit Metadata", "Visibility"])
```

---

### `streamlit_ui/db/repository/experiment_repository.py` (repository, MODIFY -- US-5)

**Analog:** self

**Key additions:**
- `list_rich()` method returning experiment + relationships (USES_MODEL, USES_RECIPE, USES_TECHNIQUE, checkpoint count)
- Remove or deprecate `create()` / `create_experiment()` (hook-only)
- Restrict `update()` to description/notes fields only

**Rich browse query** (from RESEARCH.md):
```cypher
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

---

### `streamlit_ui/ui_pages/checkpoints.py` (component, NEW -- US-6)

**Analog:** `ui_pages/models.py` (lines 1-209, full file pattern)

**Copy this exact structure:**
1. Imports block (lines 1-13 of models.py)
2. Async helper functions (one per repository method)
3. `run()` function with tabs

**Tab structure for checkpoints:**
```python
tab_browse, tab_uri_edit, tab_visibility = st.tabs(["Browse", "URI Edit", "Visibility"])
```

**Browse should show:** epoch, run, metrics, URI, parent experiment, used_by experiments.

**URI Edit wizard pattern** (from CONTEXT.md US-6):
- Show current URI
- Input new URI
- Preview with deps (show STARTED_FROM experiments)
- Checkbox confirm
- Apply

**Soft-delete pattern:** Same as experiments -- toggle `is_usable` with dependency warnings.

---

### `streamlit_ui/db/repository/checkpoint_repository.py` (repository, NEW -- US-6)

**Analog:** `db/repository/model_repository.py` (lines 1-332, full file)

**Copy this class skeleton:**
```python
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class CheckpointRepository:
    def __init__(self, db_client: AsyncNeo4jClient):
        self.db = db_client

    async def list_all(self, experiment_id: Optional[str] = None, usable_only: bool = False) -> list[dict]: ...
    async def get_by_id(self, ckp_id: str) -> Optional[dict]: ...
    async def update_uri(self, ckp_id: str, new_uri: str) -> dict: ...
    async def set_usable(self, ckp_id: str, is_usable: bool) -> dict: ...
    async def get_dependencies(self, ckp_id: str) -> list[dict]: ...
```

**Browse query** (from RESEARCH.md):
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

---

### `streamlit_ui/ui_pages/graph_viz.py` (component, NEW -- US-7)

**No existing analog in codebase.**

**Imports** (from RESEARCH.md):
```python
from __future__ import annotations

import logging
import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config

from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.async_helpers import run_async

logger = logging.getLogger(__name__)
```

**Core pattern** (from RESEARCH.md):
```python
nodes = [Node(id=exp_id, label=exp_id, size=25, color="#4CAF50") for ...]
edges = [Edge(source=child_id, target=parent_id, label="DERIVED_FROM") for ...]
config = Config(directed=True, hierarchical=True, physics=False)
agraph(nodes=nodes, edges=edges, config=config)
```

**Page structure:** Follow same `run()` function pattern as all other pages.

---

### `streamlit_ui/ui_pages/admin.py` (component, NEW -- US-11)

**Analog:** `ui_pages/experiments.py` (browse pattern with filters)

**Purpose:** Run integrity check queries and display results with corrective action buttons.

**Page structure:**
```python
def run() -> None:
    st.title("Admin Console")
    tab_integrity, = st.tabs(["Integrity Checks"])
```

**Integrity queries** from RESEARCH.md (5 checks, each a separate expander with results + action buttons).

---

### `streamlit_ui/app.py` (config, MODIFY)

**Analog:** self

**Changes needed:**
1. Replace `asyncio.run(ensure_schema_initialized())` with `run_async(ensure_schema_initialized())`
2. Add new pages to sidebar nav: "Checkpoints", "Graph", "Admin"
3. Remove Health Check (already absent)
4. Add dynamic imports for new pages

**Current nav pattern** (lines 98-103):
```python
page_options = [
    "Recipes",
    "Models",
    "Experiments",
    "Components",
]
```

**Current page loading pattern** (lines 116-127):
```python
if page == "Recipes":
    from graph_lineage.streamlit_ui.ui_pages import recipes
    recipes.run()
elif page == "Models":
    from graph_lineage.streamlit_ui.ui_pages import models
    models.run()
```

---

## Shared Patterns

### Async Helper (apply to ALL page files)
**Source:** New `streamlit_ui/utils/async_helpers.py`
**Apply to:** `app.py`, `models.py`, `recipes.py`, `experiments.py`, `components.py`, `checkpoints.py`, `graph_viz.py`, `admin.py`
```python
from graph_lineage.streamlit_ui.utils.async_helpers import run_async

# Replace every asyncio.run(some_coro()) with:
run_async(some_coro())
```

### Error Handling
**Source:** `streamlit_ui/utils/errors.py` (lines 5-17)
**Apply to:** All page and repository files
```python
from graph_lineage.streamlit_ui.utils.errors import UIError

try:
    # CRUD op
except UIError as e:
    st.error(f"Error: {e.user_message}")
    st.caption(e.details)
```

### Repository Constructor
**Source:** `db/repository/model_repository.py` (lines 16-22)
**Apply to:** `checkpoint_repository.py` (new)
```python
class XRepository:
    def __init__(self, db_client: AsyncNeo4jClient):
        self.db = db_client
```

### History Repository Import (dual-repo pattern)
**Source:** `history/repository.py` (lines 53-59)
**Apply to:** `experiments.py` page, `checkpoints.py` page, `admin.py` page
```python
from graph_lineage.history.repository import ExperimentRepository as HistoryRepository

# Instantiate with same client:
db_client = get_neo4j_client()
history_repo = HistoryRepository(db_client)
```

### Soft-Delete UI Pattern
**Apply to:** `experiments.py` (US-5), `checkpoints.py` (US-6)
```python
# Toggle visibility with confirmation
current_usable = entity.get("usable", True)
new_state = not current_usable
label = "Restore" if not current_usable else "Hide"

if st.button(f"{label} {entity_name}", key=f"vis_{entity_id}"):
    confirm = st.checkbox(f"Confirm {label.lower()}?", key=f"confirm_vis_{entity_id}")
    if confirm:
        run_async(history_repo.set_visibility(entity_id, new_state))
        st.success(f"Entity {label.lower()}d!")
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `streamlit_ui/ui_pages/graph_viz.py` | component | request-response | No graph visualization exists; use streamlit-agraph API from RESEARCH.md |
| `streamlit_ui/utils/async_helpers.py` | utility | -- | New utility; pattern defined in RESEARCH.md |

## Metadata

**Analog search scope:** `graph_lineage/streamlit_ui/`, `graph_lineage/history/`
**Files scanned:** 12
**Pattern extraction date:** 2026-05-12
