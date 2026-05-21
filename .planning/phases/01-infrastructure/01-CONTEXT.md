# Phase 1: Infrastructure Consolidation - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix broken imports, consolidate duplicates, and establish storage abstraction. Prepares codebase for Config Schema (Phase 2) and Hook/Decorator (Phase 4).

WORK STATUS: ~95% structurally complete from previous session. Staged but not committed. Needs verification + finalization.

</domain>

<decisions>
## Implementation Decisions

### Code Structure Migration
- **D-01:** Rename `graph_lineage/data_class/` → `graph_lineage/data_classes/` (node + edge models)
- **D-02:** Update all repository imports to use `data_classes` path (already done in recipe_validation.py, recipe_repository.py)
- **D-03:** Remove duplicate Cypher files — keep only `01-schema.cypher`, `02-triggers.cypher` (old duplicates already deleted)
- **D-04:** Fix pyproject.toml `packages = ["graph_lineage"]` (already done)

### Storage Abstraction
- **D-05:** StorageProvider ABC interface sufficient — no separate resolver.py needed
  - 8 abstract methods: exists, read_text, read_bytes, write_text, write_bytes, list_files, walk, is_dir, is_writable, backup
  - Decoder: Users extend StorageProvider for new backends (SSH, S3); no factory pattern at this stage
- **D-06:** LocalStorageProvider implementation complete — handles base_path resolution, directory creation, backup timestamps
- **D-07:** Export StorageProvider + LocalStorageProvider from `graph_lineage/__init__.py` for easy imports

### Documentation
- **D-08:** README: 1-2 sentence mention only — "Storage is abstracted; local FS supported, future backends via StorageProvider"
- **D-09:** Deferred: Detailed docs + examples (Phase 4+ when decorator is live)

### Verification
- **D-10:** Run `tests/test_storage.py` now to verify storage layer works before Phase 2
  - Catches import/implementation issues early
  - Confidence gate before proceeding

</decisions>

<canonical_refs>
## Canonical References

### Phase 1 Requirements
- `.planning/ROADMAP.md` §PHASE 1 — Infrastructure tasks 1.1-1.9
- `.planning/REQUIREMENTS.md` — Storage abstraction requirement (v1.0 deliverable)
- `.planning/PROJECT.md` §Appendix — Naming conventions (checkpoint paths, artifact URIs)

### Storage Design Reference
- `graph_lineage/storage/provider.py` — StorageProvider ABC (8 methods documented)
- `graph_lineage/storage/local_provider.py` — LocalStorageProvider implementation (complete)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `graph_lineage/data_classes/neo4j/nodes/recipe.py` — Pydantic Recipe model (will reuse in Phase 2 Config)
- `graph_lineage/data_classes/neo4j/nodes/model.py`, `experiment.py`, `component.py` — Entity models ready for Phase 4
- `tests/test_storage.py` — Storage provider test suite (7.9K, ready to execute)

### Established Patterns
- **Import structure:** `from graph_lineage.data_classes.neo4j.nodes import Recipe` (already active)
- **Storage interface:** StorageProvider ABC decouples business logic from physical storage
- **Pydantic models:** All entities use Pydantic v2 for validation (consistent across codebase)

### Integration Points
- **Phase 2 (Config Schema):** Will import `StorageProvider` to read/write config YAML
- **Phase 4 (Hook/Decorator):** Will use `LocalStorageProvider` to snapshot training files, read metrics
- **Phase 5 (E2E Testing):** Will mock `StorageProvider` for deterministic test scenarios

</code_context>

<specifics>
## Specific Ideas

- "Storage abstraction should make it trivial to add SSH or S3 backend later without touching Phase 4+ logic"
- Use LocalStorageProvider with base_path for reproducible test snapshots (Phase 5)

</specifics>

<deferred>
## Deferred Ideas

- Separate resolver/factory module — deferred until third storage backend needed (likely Phase 1.2 or later milestone)
- Detailed storage documentation + code examples — Phase 4 when decorator is live and storage is actively used
- Storage provider caching layer (for remote backends) — Phase 1.2 optimization

</deferred>

---

*Phase: 01-infrastructure*
*Context gathered: 2026-04-21*
