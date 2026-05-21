---
phase: 05-ui-redesign
plan: 02
subsystem: ui
tags: [streamlit, neo4j, cypher, merge, upsert, crud]

requires:
  - phase: 05-01
    provides: "run_async helper, 9-page navigation, asyncio.run replacement"
provides:
  - "Model upsert by model_name using MERGE Cypher"
  - "Recipe upsert by URI using MERGE Cypher"
  - "Hardened Component page with proper empty states and CTA labels"
affects: [05-03, 05-04, 05-05]

tech-stack:
  added: []
  patterns: ["MERGE Cypher upsert with ON CREATE/ON MATCH SET", "Upsert toggle checkbox in form"]

key-files:
  created: []
  modified:
    - graph_lineage/streamlit_ui/db/repository/model_repository.py
    - graph_lineage/streamlit_ui/ui_pages/models.py
    - graph_lineage/streamlit_ui/db/repository/recipe_repository.py
    - graph_lineage/streamlit_ui/ui_pages/recipes.py
    - graph_lineage/streamlit_ui/ui_pages/components.py

key-decisions:
  - "Model upsert ON MATCH uses CASE to preserve existing non-empty fields"
  - "Recipe upsert ON MATCH overwrites all fields unconditionally (URI is authoritative)"
  - "Upsert by URI added as separate tab in recipes page to preserve YAML upload flow"

patterns-established:
  - "Upsert pattern: MERGE on natural key, ON CREATE SET all fields, ON MATCH SET conditionally"
  - "Upsert UI pattern: checkbox toggle in form to switch between create and upsert"

requirements-completed: [US-2, US-3, US-4]

duration: 2min
completed: 2026-05-12
---

# Phase 05 Plan 02: CRUD Hardening Summary

**Model upsert by model_name and Recipe upsert by URI using MERGE Cypher, plus Component page hardening with proper CTA labels and empty states**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-12T13:13:53Z
- **Completed:** 2026-05-12T13:16:04Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Model CRUD page supports upsert by model_name via MERGE Cypher with conditional field updates
- Recipe CRUD page has new "Upsert by URI" tab with MERGE Cypher, existing YAML upload preserved
- Component page hardened with "Save Component" CTA and descriptive empty state message

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Model upsert by name (US-2)** - `f4958d0` (feat)
2. **Task 2: Add Recipe upsert by URI (US-3) + Component hardening (US-4)** - `ef15e90` (feat)

## Files Created/Modified
- `graph_lineage/streamlit_ui/db/repository/model_repository.py` - Added upsert_by_name() with MERGE Cypher
- `graph_lineage/streamlit_ui/ui_pages/models.py` - Added upsert toggle in Create tab, "Save Model" CTA
- `graph_lineage/streamlit_ui/db/repository/recipe_repository.py` - Added upsert_by_uri() with MERGE Cypher
- `graph_lineage/streamlit_ui/ui_pages/recipes.py` - Added "Upsert by URI" tab with form
- `graph_lineage/streamlit_ui/ui_pages/components.py` - Updated CTA to "Save Component", descriptive empty state

## Decisions Made
- Model upsert uses CASE expressions in ON MATCH SET to preserve existing non-empty values when new values are empty strings
- Recipe upsert overwrites all fields on match since URI is the authoritative source
- Added "Upsert by URI" as a separate tab rather than modifying the YAML upload flow

## Deviations from Plan

None - plan executed exactly as written.

## Threat Model Compliance

Both upsert methods use parameterized Cypher queries ($model_name, $uri) - no string interpolation. T-05-02 and T-05-03 mitigations applied.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Upsert infrastructure ready for use by experiment and checkpoint pages
- All three entity pages (Model, Recipe, Component) now follow consistent patterns

---
*Phase: 05-ui-redesign*
*Completed: 2026-05-12*
