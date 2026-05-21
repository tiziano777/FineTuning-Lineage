# FineTuning-Lineage Project

## Vision
A production-grade experiment lineage tracking system for LLM fine-tuning that combines:
- **Hook-based observability**: Decorator-driven tracking of training runs
- **Neo4j dependency graph**: Full experiment history + reproducibility
- **Config-driven metadata**: YAML-based experiment configuration with automatic DB sync
- **Differencing logic**: Intelligent detection of RETRY vs BRANCH vs NEW runs
- **Modular storage abstraction**: Support for local FS + future SSH/S3/GCS

**Goal**: Enable users to run training with 1 decorator, automatically track:
- Experiment lineage (NEW → BRANCH → RETRY → MERGE chains)
- Checkpoint history + metrics
- Code + config diffs between runs
- Hardware + training metrics per run

---

## Project Status

### v0.x (Pre-v1.0)
- ✅ Neo4j schema defined (5 node types, 6 relationships, triggers)
- ✅ Streamlit UI skeleton (CRUD for recipes, models, components, experiments)
- ⚠️ **BROKEN**: Import paths mismatched after restructuring
- ❌ **MISSING**: Core hook/decorator system
- ❌ **MISSING**: DiffManager + branching logic
- ❌ **MISSING**: Config schema + validation

### v1.0 milestone (THIS WORK)
- **Start date**: 2026-04-20
- **Target completion**: 2026-04-27 (assuming 4h/day focused work)
- **Phases**: 8 (infrastructure → documentation → polish → commit)
- **Test coverage**: >80% unit + integration
- **Deliverable**: Production-ready hook + DiffManager + local Neo4j support

**After v1.0**, we move to:
- v1.1: Async refactor
- v1.2: Remote worker communication (SSH/TCP)
- v2.0: Advanced UI (visualization, query builder)

---

## Key Decisions

### Architecture
- **Monolithic first**: All code in `envelope/` + `graph_lineage/`
- **Config YAML as source of truth**: Experiment metadata flows YAML → Entity → DB
- **Storage abstraction from day 1**: Even though we only implement local FS now
- **DiffManager as decision engine**: All branching logic centralized, testable
- **Decorator over instrumentation**: Easy to adopt for users (just add @decorator)

### Configuration
- **Namespace structure**: `experiment.*`, `model.*`, `recipe.*`, `output.*`, `hardware.*`, `model_merging.*`
- **Write-back pattern**: Decorator updates config.yml with generated UUIDs
- **Validation strict PRE-EXECUTION**: Fail fast with clear exit codes

### Error Handling
- **Exit codes**: 0 (success), 1 (train crash), 2 (validation), 3 (storage), 4 (DB), 5 (logic conflict)
- **Markdown error guide**: docs/ERROR_HANDLING.md for end-user troubleshooting
- **Logging comprehensive**: All decisions logged with stacktraces on failure

### Testing
- **Unit tests**: All business logic (DiffManager, RuleEngine, validation)
- **Integration tests**: Full flow (config → decorator → Neo4j → UI)
- **E2E scenarios**: 5 paths (NEW, RETRY, BRANCH, RESUME, MERGE)
- **Target coverage**: >80% for core modules

---

## Success Criteria

### Functional
- [ ] Decorator can be added to any training function
- [ ] Config.yml is read, validated, and updated atomically
- [ ] DiffManager correctly identifies RETRY vs BRANCH (all 4 cases + merge)
- [ ] Experiment nodes created in Neo4j with correct relationships
- [ ] All 5 run scenarios work end-to-end locally
- [ ] Exit codes match specification
- [ ] Error messages are clear + actionable

### Quality
- [ ] All unit tests pass (>80% coverage)
- [ ] All integration tests pass
- [ ] Code review clean (no security issues, no complexity red flags)
- [ ] Documentation complete (MIDDLEWARE.md, CONFIG.md, EXAMPLES.md)
- [ ] README updated with architecture + quick start

### Non-functional
- [ ] No blocking external dependencies (all optional)
- [ ] Local Neo4j startup via docker-compose
- [ ] Storage abstraction allows future remote schemes
- [ ] Decorator overhead <100ms per run startup

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Config writing causes data loss | HIGH | Atomic write pattern + backup original before write |
| DiffManager logic too complex | HIGH | Start simple, add cases iteratively, extensive unit tests |
| Neo4j unavailable blocks training | MEDIUM | Graceful degradation (warn, log, allow train to continue) |
| Storage URIs invalid | MEDIUM | PRE-EXECUTION validation + clear BlockMessage on error |
| Snapshot serialization huge | MEDIUM | Store only critical files (4 files max) |

---

## Team & Communication

- **Solo**: Primarily you implementing, code review via code-review-graph
- **Decision gates**: After each phase (PLAN review before EXECUTE)
- **Async**: All work tracked in git + .planning/ artifacts

---

## Appendix: Naming Conventions

- **Experiment node UUID**: Auto-generated UUID (Python uuid.uuid4())
- **Checkpoint naming**: `{model_name}_ckp_{serial}_{exp_uuid}`
  - serial: 0, 1, 2, ... (per experiment)
  - exp_uuid: short form (first 8 chars)
  - Example: `llama7b_ckp_0_e2f54a3a`
- **Relationship properties**:
  - DERIVED_FROM: `{diff_patch: JSON, commit_msg: str (optional)}`
  - PRODUCED_BY: `{metrics_uri: str, hw_metrics_uri: str}`
- **Exit codes**: 0, 1, 2, 3, 4, 5 (see REQUIREMENTS.md)

---

## Milestones Tracker

### v1.0 (Current)
- [ ] Phase 1: Infrastructure (fix imports, populate configs, storage abstraction)
- [ ] Phase 2: Config Schema (Pydantic models, validation, write-back)
- [ ] Phase 3: DiffManager (snapshot, diff_match_patch, rule engine)
- [ ] Phase 4: Hook/Tracker (decorator, Neo4j integration)
- [ ] Phase 5: Integration & E2E (5 scenarios, manual testing)
- [ ] Phase 6: Documentation (middleware, config, examples)
- [ ] Phase 7: Polish (code review, linter, coverage)
- [ ] Phase 8: Commit & Prepare (atomic commits, PR)

### v1.1 (Future)
- [ ] Async refactor (asyncio.run decorators on all async code)

### v1.2 (Future)
- [ ] Remote worker communication (SSH, HTTP, TCP abstractions)

### v2.0 (Future)
- [ ] Advanced UI (visualization, lineage browser, diff viewer)
