# Phase 5: Streamlit UI Redesign — Context

## Decision Log

- Health Check page removed from nav (was never implemented)
- `streamlit-agraph` chosen for graph visualization (US-7)
- UI and DB run on separate servers — no config.yml access from UI
- Hook client sends dataclass objects, not files
- Soft-delete via `usable`/`is_usable` flag on Experiment + Checkpoint
- Experiment creation is read-only from UI (only hook creates)
- Checkpoint creation is read-only from UI (only hook creates)

## Approved User Stories

### Tier 1 — Foundations (P0)

| US | Title | Status |
|----|-------|--------|
| US-1 | Fix asyncio (run_async helper + nest_asyncio) | Approved |
| US-2 | Model CRUD + upsert by model_name | Approved |
| US-3 | Recipe CRUD + upsert by URI (preserve YAML upload) | Approved |
| US-4 | Component CRUD hardening (minimal) | Approved |
| US-5 | Experiment read-only + edit description/notes + soft-delete + integrity check DB-side | Approved — detailed |
| US-6 | Checkpoint browse + URI edit wizard + soft-delete (is_usable) + dependency warning | Approved — detailed |

### Tier 2 — Visualization + History (P1)

| US | Title | Status |
|----|-------|--------|
| US-7 | Graph visualization (streamlit-agraph DAG) | Pending design |
| US-8 | History navigation (back/forward + codebase reconstruct) | Pending design |
| US-9 | Rollback wizard (preview → confirm → apply) | Pending design |
| US-10 | Squash wizard (from/to → preview → confirm) | Pending design |

### Tier 3 — Admin (P2)

| US | Title | Status |
|----|-------|--------|
| US-11 | Admin console: consistency check on URI fields + corrective actions | Pending design |

## US-5 Design (Experiment)

### Browse
- Rich view: experiment + USES_MODEL + USES_RECIPE + USES_TECHNIQUE + checkpoint count
- Filter by status, model, search
- Badge "HIDDEN" for usable=false experiments

### Edit Metadata
- Editable: description, manual notes
- NOT editable: exp_id, config_hash, code_hash, status, timestamps, relations

### Soft-Delete
- Hide → usable=false (single node)
- Restore → usable=true + restore ancestor chain (via history/repository.py:set_visibility)
- Warning if downstream DERIVED_FROM children exist

### Integrity Check (DB-side only)
1. Experiments without USES_MODEL or USES_RECIPE
2. Referenced Model/Recipe not existing in DB
3. Status=RUNNING for >X hours (probably crashed)
4. Duplicate config_hash without RETRY_OF edge
5. No DERIVED_FROM/RETRY_OF cycles

## US-6 Design (Checkpoint)

### Browse
- Filter by experiment, usable status
- Show epoch, run, metrics, URI, parent experiment
- Show used_by (experiments with STARTED_FROM → this ckp)

### URI Edit (critical operation)
- Wizard: show current URI → input new → preview with deps → checkbox confirm → apply

### Soft-Delete
- Check STARTED_FROM dependencies → warn
- Check if "best checkpoint" of experiment → warn
- Toggle is_usable=false with confirm
- Restore: toggle back to true

## Existing Code Issues Found

1. asyncio.run() antipattern in all ui_pages/*.py
2. Two separate ExperimentRepository classes (UI CRUD vs history ops) not connected
3. Experiment create asks model_id as free text (should be selectbox)
4. No Checkpoint page exists
5. No graph visualization
6. No admin console / consistency check
7. No upsert support
