# ROADMAP.md — v1.0 Execution Plan

**Milestone**: Core Lineage Tracking System v1.0
**Start Date**: 2026-04-20
**Target Completion**: 2026-04-27 (25-30 hours, 4-8 hours/day)
**Format**: GSD (Get Shit Done) with phase-based execution

---

## Phase Breakdown

```
MILESTONE 1 (This Work)
├─ PHASE 1: Infrastructure Consolidation (2-3h) ✅
├─ PHASE 2: Config Schema & Validation (1.5-2h) ✅
├─ PHASE 3: DiffManager System (2.5-3h) ✅
├─ PHASE 4: Hook/Decorator (3.5-4h) ✅
├─ PHASE 5: Streamlit UI Redesign (5 plans, 3 waves) ✅
├─ PHASE 6: Integration & E2E Testing (4 plans, 3 waves)
├─ PHASE 7: Documentation (1.5-2h)
├─ PHASE 8: Polish & Verification (1h)
└─ PHASE 9: Commit & Prepare (0.5h)
```

---

## PHASE 1: Infrastructure Consolidation

**Goal**: Fix broken imports, consolidate duplicates, and establish storage abstraction
**Estimate**: 2-3h
**Status**: Planning complete, ready for execution
**Success Criteria**:
- [ ] All imports pass pylance (no red squiggles)
- [ ] Code graph rebuilds successfully
- [ ] Duplicate Cypher files consolidated
- [ ] pyproject.toml references correct packages
- [ ] StorageProvider abstraction implemented + tested

**Plans**:
- [x] 01-01-PLAN.md — Fix imports, finalize storage exports, run tests (3 tasks)

**Requirements Covered**: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9

**Deliverables**:
- `.planning/phases/01-infrastructure/01-01-PLAN.md` (executable plan)
- Fixed codebase (no import errors)
- StorageProvider working locally
- All storage tests passing

**Depends On**: Nothing (can start immediately)

**Tasks Blocking**: All other phases

---

## PHASE 2: Config Schema & Validation

**Goal**: Create Pydantic config models, validation logic, and write-back mechanism
**Estimate**: 1.5-2h
**Status**: ✅ Implemented — pending test confirmation (pytest blocked by hook)
**Success Criteria**:
- [x] LineageConfig model parses all fields correctly
- [x] All 10+ validation errors caught (exit 2/3/5)
- [x] config.yml updated with UUIDs atomically
- [x] StorageProvider integration works

**Plans**:
- [x] 02-01-PLAN.md — Schema + validator + atomic writer (4 tasks)

**Deliverables**:
- `.planning/phases/02-config/02-01-PLAN.md` (executable plan)
- working LineageConfig + validator
- config write-back working

**Depends On**: PHASE 1 (storage resolver)

---

## PHASE 3: DiffManager System

**Goal**: Implement codebase snapshots, unified diff generation, hash-based change detection, auto-generated descriptions, and codebase reconstruction from lineage chain
**Estimate**: 2.5-3h
**Status**: Planning complete, ready for execution
**Success Criteria**:
- [ ] Snapshot captures 4 critical files correctly
- [ ] Unified diffs generated via difflib.unified_diff
- [ ] SHA-256 hashes computed for change detection
- [ ] Auto-generated description messages from YML config
- [ ] Codebase reconstruction from lineage chain works (round-trip verified)

**Plans**: 2 plans
- [x] 03-01-PLAN.md — Fix Experiment model, create CodebaseSnapshot + Differ (2 tasks)
- [x] 03-02-PLAN.md — YML message loader + description generator + reconstructor (2 tasks)

**Requirements Covered**: R3.1, R3.2, R3.2+

**Deliverables**:
- `.planning/phases/03-diffmanager-system/03-01-PLAN.md` (executable plan)
- `.planning/phases/03-diffmanager-system/03-02-PLAN.md` (executable plan)
- Fixed Experiment model (bugs + field renames + base:bool)
- CodebaseSnapshot + Differ modules working
- Message templates + loader with user override
- Codebase reconstructor with round-trip test
- Test coverage >80%

**Depends On**: PHASE 1 (storage)

---

## PHASE 4: Hook/Decorator System

**Goal**: Implement @envelope.tracker() decorator with full PRE/POST phases
**Estimate**: 3.5-4h
**Success Criteria**:
- [ ] Decorator can be added to training function
- [ ] PRE-EXECUTION: config loaded, validated, Experiment node created
- [ ] POST-EXECUTION: metrics read, checkpoints created, status updated
- [ ] Failure handling: status = FAILED, exit code 1
- [ ] config.yml updated with UUIDs
- [ ] All exit codes (0,1,2,3,4,5) correct

**Tasks**:
1. **4.1** Create: `envelope/lineage/neo4j_manager.py` (DB operations)
2. **4.2** Implement: create_experiment_node, update_status, link_relationships
3. **4.3** Implement: create_checkpoint_node, create_merged_checkpoint
4. **4.4** Implement: Recipe/Model/Component node creation (if not exists)
5. **4.5** Create: `envelope/lineage/tracking_context.py` (state machine)
6. **4.6** Implement: States (NOT_STARTED → VALIDATED → RUNNING → COMPLETED/FAILED)
7. **4.7** Create: `envelope/lineage/tracker.py` (decorator + lifecycle)
8. **4.8** Implement: PRE-EXECUTION phase (validation, DiffManager, node creation)
9. **4.9** Implement: POST-EXECUTION phase (metrics + checkpoints)
10. **4.10** Implement: Failure handler (status update + exit)
11. **4.11** Create: `envelope/lineage/__init__.py` (export decorator)
12. **4.12** Unit tests: All phases + error cases
13. **4.13** Mock training function tests

**Deliverables**:
- `.planning/phases/04-decorator/PLAN.md`
- @envelope.tracker() decorator working
- PRE/POST phases working
- Neo4j integration tested
- Test coverage >80%

**Depends On**: PHASE 2 (config), PHASE 3 (DiffManager)

---

## PHASE 5: Streamlit UI Redesign

**Goal**: Redesign and harden the Streamlit UI — fix asyncio antipatterns, add graph visualization, integrate history operations, add admin console with consistency checks
**Estimate**: TBD (iterative — multiple sub-plans)
**Status**: Planning complete
**Plans:** 5 plans

Plans:
- [x] 05-01-PLAN.md — Async helper (run_async + nest_asyncio), theme, app.py nav update, stub pages
- [x] 05-02-PLAN.md — Model upsert by name, Recipe upsert by URI, Component hardening
- [x] 05-03-PLAN.md — Experiment read-only overhaul + Checkpoint page creation
- [x] 05-04-PLAN.md — Graph visualization (streamlit-agraph) + History wizards (navigate/rollback/squash)
- [x] 05-05-PLAN.md — Admin console with 5 integrity checks + human verification checkpoint

**Success Criteria**:
- [ ] asyncio.run() antipattern eliminated (single event loop)
- [ ] CRUD pages for Model, Recipe, Component hardened with upsert support
- [ ] Experiment page: read-only (hook-created), with metadata enrichment from UI
- [ ] Checkpoint page: read-only browse + URI edit (critical op with confirmation)
- [ ] Recipe upload from YAML file working (preserve existing)
- [ ] Model upsert by name (from config file or UI)
- [ ] Recipe upsert by URI (from config file or UI)
- [ ] Graph visualization of experiment lineage chains
- [ ] History operations (rollback, squash, navigate) exposed via wizard UI
- [ ] Admin console: consistency check on experiment URIs (output_dir, metrics_uri, output_dir)
- [ ] All pages tested

**Depends On**: PHASE 4 (hook/decorator)

---

## PHASE 6: Integration & E2E Testing

**Goal**: Fix all failing tests, correct server base_experiment_id logic, and implement 7 sequential integration scenarios (S-01 through S-07) covering NEW, RETRY, BRANCH, RESUME, and MERGE strategies.
**Estimate**: 2.5-3h
**Status**: Planning complete
**Plans:** 4 plans

Plans:
- [x] 06-01-PLAN.md — Fix 10 failing tests (Group A: rule_engine, Group B: server_api, Group C: checkpoint, Group D: e2e)
- [ ] 06-02-PLAN.md — Server fix: base_experiment_id self-reference for NEW + integration_new assertions
- [ ] 06-03-PLAN.md — Test infrastructure (logs/, ckp_factory, codebase_mutator fixtures) + S-01, S-02
- [ ] 06-04-PLAN.md — Merge infrastructure (mock_neo4j, merge_client) + S-03, S-04, S-05, S-06, S-07

**Success Criteria**:
- [ ] 0 failing tests in pytest tests/
- [ ] base_experiment_id == experiment_id for all NEW strategy experiments
- [ ] S-01 (NEW→RETRY→RETRY): 2 RETRY_OF edges, 0 checkpoints
- [ ] S-02 (NEW→BRANCH→BRANCH): 2 DERIVED_FROM edges with diff_patch
- [ ] S-03 (NEW→BRANCH+ckp): DERIVED_FROM + STARTED_FROM + PRODUCED
- [ ] S-04 (NEW→RETRY→RESUME): RETRY_OF + STARTED_FROM pointing to ckp
- [ ] S-05 (MERGE intra-exp): MERGED_FROM x2, no PRODUCED from training
- [ ] S-06 (MERGE inter-exp + PROMOTED_TO): MERGED_FROM x2 + PROMOTED_TO Model
- [ ] S-07 (Full tree): all relationship types + no-circular-deps assertion

**Depends On**: PHASE 5 (UI), PHASE 4 (decorator)

---

## PHASE 7: Documentation

**Goal**: Write comprehensive user + developer documentation
**Estimate**: 1.5-2h
**Success Criteria**:
- [ ] docs/MIDDLEWARE.md complete (architecture + examples)
- [ ] docs/CONFIG.md complete (reference + field descriptions)
- [ ] docs/EXAMPLES.md complete (all 4+ scenarios)
- [ ] docs/ERROR_HANDLING.md complete (user-facing troubleshooting)
- [ ] README.md updated with architecture
- [ ] All docs have code examples

**Tasks**:
1. **7.1** Create: `docs/MIDDLEWARE.md` (architecture + decorator usage)
2. **7.2** Create: `docs/CONFIG.md` (config.yml reference)
3. **7.3** Create: `docs/EXAMPLES.md` (4 scenarios + output)
4. **7.4** Create: `docs/ERROR_HANDLING.md` (exit codes + fixes)
5. **7.5** Update: README.md (architecture diagram + quick start)
6. **7.6** Update: workflow.md (dev workflow)
7. **7.7** Review all docs for clarity + completeness

**Deliverables**:
- `.planning/phases/07-documentation/PLAN.md`
- All docs written + reviewed
- Code examples working
- User can follow from start to finish

**Depends On**: PHASE 6 (everything working)

---

## PHASE 8: Polish & Verification

**Goal**: Code review, test coverage verification, final cleanup
**Estimate**: 1h
**Success Criteria**:
- [ ] No linter warnings (ruff)
- [ ] Test coverage >80% on core modules
- [ ] Code review clean (no security/quality issues)
- [ ] All tests pass
- [ ] Documentation reviewed for accuracy

**Tasks**:
1. **8.1** Run: `ruff check envelope/ tests/`
2. **8.2** Fix any linter warnings
3. **8.3** Run: `pytest --cov envelope/ tests/`
4. **8.4** Add tests for coverage gaps (<80%)
5. **8.5** Code review via code-review-graph
6. **8.6** Fix any findings
7. **8.7** Final manual test (full E2E)

**Deliverables**:
- `.planning/phases/08-polish/PLAN.md`
- No linter warnings
- Test coverage >80%
- Code review clean

**Depends On**: PHASE 7 (documentation)

---

## PHASE 9: Commit & Prepare

**Goal**: Organize commits, create PR, prepare for merge
**Estimate**: 0.5h
**Success Criteria**:
- [ ] Feature branch with atomic commits
- [ ] PR created with test report
- [ ] Commit messages clear + linked to requirements

**Tasks**:
1. **9.1** Create feature branch: `feature/core-lineage-tracking`
2. **9.2** Organize commits:
   - Commit 1: "refactor: fix imports + consolidate Cypher"
   - Commit 2: "feat: add StorageProvider abstraction"
   - Commit 3: "feat: add LineageConfig Pydantic models"
   - Commit 4: "feat: implement CodeSnapshot + DiffAnalyzer"
   - Commit 5: "feat: implement RuleEngine (branching logic)"
   - Commit 6: "feat: add @envelope.tracker() decorator"
   - Commit 7: "test: integration tests E2E"
   - Commit 8: "docs: add middleware + config documentation"
   - Commit 9: "fix: code review + test coverage"
3. **9.3** Create PR with test report
4. **9.4** Update MEMORY.md + PROJECT.md (mark complete)

**Deliverables**:
- `.planning/phases/09-commit/PLAN.md`
- Feature branch with 9 atomic commits
- PR ready for review
- All artifacts updated

**Depends On**: PHASE 8 (everything complete)

---

## Timeline Estimate

| Phase | Hours | Cumulative | By Day (4h/day) |
|-------|-------|-----------|-----------------|
| 1     | 2-3   | 2-3       | Day 1           |
| 2     | 1.5-2 | 3.5-5     | Day 1-2         |
| 3     | 2.5-3 | 6-8       | Day 2           |
| 4     | 1/2 | Done |  |
| 5 (UI)| TBD   | Iterative | TBD             |
| 6     | 2.5-3 | —         | —               |
| 7     | 1.5-2 | —         | —               |
| 8     | 1     | —         | —               |
| 9     | 0.5   | —         | —               |
| **Total (code)** | **16-17** | **16-17** | **Day 1-5** |
| Tests (40% overhead) | 6-7 | 22-24 | Day 5-7 |
| Manual + fixes | 2-3 | 25-30 | Day 7-8 |
| **GRAND TOTAL** | **25-30** | | **4-8 days @ 4h/day** |

---

## Git Strategy

**Per-Phase Branching**: One feature branch for entire milestone
**Commit Strategy**: 9 atomic commits (1 per task group)
**PR Strategy**: Single PR with full test report at end

**Branch**: `feature/core-lineage-tracking`
**Base**: `main`

---

## Approval Gate

**PHASE 1 is PLANNED**: Ready for execution

Next: `/gsd-execute-phase 1`

---

**Status**: Phase 5 COMPLETE. Phase 6 PLANNED. Next: Phase 6 (Integration E2E).
