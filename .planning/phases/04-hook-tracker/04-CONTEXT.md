---
phase: 04-hook-tracker
status: planned
---

# Phase 04: Hook/Tracker — Context

## Goal
Implement the `@envelope.tracker(blocking=True)` decorator that orchestrates:
1. **PRE-EXECUTION**: Load config → validate → snapshot codebase → detect run type → create Neo4j nodes
2. **RUN**: Execute user training function
3. **POST-EXECUTION**: Update experiment status (COMPLETED/FAILED), capture exit info

## Key Design Decisions

### blocking parameter
- `blocking=True` (default): Any error (validation, DB unreachable, snapshot fail) → log + exit with specific code
- `blocking=False`: Any error → log warning, skip lineage, let training proceed in "detached mode"

### Sync-only PRE-execution
The decorator wraps sync training functions. Neo4j calls use `asyncio.run()` internally.

### Run Type Detection (RuleEngine)
Uses outputs from Phase 3 (diff/snapshot) + config fields to decide:
- **NEW**: No prior experiment for this URI in DB
- **RETRY**: Same hashes as parent experiment (no code change)
- **BRANCH**: Different hashes (code/config changed) → store diff_patch in DERIVED_FROM edge
- **RESUME**: `experiment.derived_from` points to a checkpoint ID
- **MERGE**: `model_merging` section present in config

### Dependencies (from completed phases)
- Phase 2: `LineageConfig`, `validate_pre_execution()`, `ConfigWriter`
- Phase 3: `CodebaseSnapshot`, `compute_snapshot_diff()`, `detect_changes()`, hash functions

## Acceptance Criteria
- [ ] `@envelope.tracker()` can decorate any `def train(config_path, device)` function
- [ ] PRE creates Experiment node with correct strategy + hashes + codebase snapshot
- [ ] RETRY/BRANCH/NEW correctly detected via hash comparison with parent
- [ ] RESUME detected when `derived_from` is a checkpoint UUID
- [ ] POST updates status to COMPLETED or FAILED with exit_msg
- [ ] `blocking=True` exits with code 2/3/4/5 on respective errors
- [ ] `blocking=False` logs warning and proceeds without lineage
- [ ] All PRE/POST Neo4j operations use existing `neo4j_client/client.py` async driver
- [ ] Unit tests with mocked Neo4j cover all 5 run types + blocking/non-blocking
