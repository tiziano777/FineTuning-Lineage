# streamlit_ui/ Module — Web UI for Neo4j Interaction

## Overview

Multi-page Streamlit web application for browsing experiments, managing configs, and visualizing lineage graph.

**Location:** `graph_lineage/streamlit_ui/`

## Public API

**Entry point:** `streamlit_ui/app.py`

```bash
streamlit run graph_lineage/streamlit_ui/app.py
# Opens http://localhost:8501
```

## Pages (9 total)

| Page | URL | Purpose |
|------|-----|---------|
| **Recipes** | /recipes | CRUD: upload, browse, edit recipes |
| **Models** | /models | CRUD: manage base models |
| **Components** | /components | CRUD: technique+framework pairs |
| **Experiments** | /experiments | READ: browse all experiments, lineage view |
| **Checkpoints** | /checkpoints | READ+EDIT: browse checkpoints, edit URIs, toggle visibility |
| **History** | /history | NAVIGATE+MUTATE: forward/back, rollback, squash |
| **Graph View** | /graph | VISUALIZE: DAG visualization (streamlit-agraph) |
| **Admin** | /admin | DIAGNOSE: integrity checks (orphans, cycles, missing edges) |
| **(implicit Home)** | / | Dashboard (TBD) |

---

## Architecture

### Async Pattern

```python
from graph_lineage.streamlit_ui.utils import run_async

async def fetch_experiments():
    repo = ExperimentRepository()
    return await repo.list_all()

# In Streamlit (sync context)
experiments = run_async(fetch_experiments())
```

### Repository Pattern

```python
# db/repository/experiment_repository.py
class ExperimentRepository:
    async def list_all(self) -> list[Experiment]:
        client = AsyncNeo4jClient()
        result = await client.run_query("MATCH (e:Experiment) RETURN e")
        return [Experiment(**row) for row in result]
```

### UI Pages Structure

```
ui_pages/
├── recipes.py          # run() function (called by app.py)
├── models.py
├── components.py
├── experiments.py
├── checkpoints.py
├── history.py
├── graph_view.py
├── admin.py
└── (home dashboard TBD)

app.py
├── Sidebar navigation (page selection)
├── Session state management (filters, caches)
├── Page dispatcher: if page == "recipes": recipes.run()
```

---

## Common Patterns

### Form Submission
```python
with st.form("my_form"):
    name = st.text_input("Name")
    submitted = st.form_submit_button("Submit")
    
    if submitted:
        result = run_async(repository.create(name=name))
        st.success(f"Created: {result}")
```

### List + Filter
```python
experiments = run_async(repo.list_all())

# Filter
status = st.selectbox("Status", ["pending", "completed", "failed"])
filtered = [e for e in experiments if e.status == status]

# Display
for exp in filtered:
    st.write(f"{exp.exp_id} — {exp.status}")
```

### Modal Confirmation
```python
if st.button("Delete"):
    st.warning("Are you sure? This cannot be undone.")
    if st.button("Confirm delete"):
        run_async(repo.delete(exp_id))
        st.success("Deleted.")
```

---

## Deployment

**Local development:**
```bash
streamlit run graph_lineage/streamlit_ui/app.py
```

**Docker:**
```bash
docker compose up streamlit -d
# Opens http://localhost:8501
```

**With authentication (future):**
```python
# Add streamlit-authenticator for multi-user setup
```

---

## Integration

**Neo4j connection:**
```python
from graph_lineage.neo4j_client import AsyncNeo4jClient

client = AsyncNeo4jClient()
# All CRUD operations go through client
```

---

## Testing

Location: `tests/test_streamlit_ui.py` (manual testing via browser recommended)

---

## See Also

- [neo4j_client.md](neo4j_client.md) — AsyncNeo4jClient details
- [data_classes.md](data_classes.md) — Node models displayed in UI
- [docker-compose.yml](../../docker-compose.yml) — Streamlit container config

