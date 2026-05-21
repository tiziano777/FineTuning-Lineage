---
phase: 03-diffmanager-system
plan: 01
subsystem: diff-infrastructure
tags: [experiment-model, snapshot, differ, tdd, pydantic]
dependency_graph:
  requires: []
  provides: [CodebaseSnapshot, capture_snapshot, compute_unified_diff, compute_file_hash, detect_changes, compute_snapshot_diff, Experiment-model-v2]
  affects: [graph_lineage/data_classes/neo4j/nodes/experiment.py, graph_lineage/diff/]
tech_stack:
  added: [difflib, hashlib]
  patterns: [frozen-pydantic-model, crlf-normalization, path-traversal-prevention]
key_files:
  created:
    - graph_lineage/diff/__init__.py
    - graph_lineage/diff/snapshot.py
    - graph_lineage/diff/differ.py
    - tests/test_experiment_model.py
    - tests/test_snapshot.py
    - tests/test_differ.py
  modified:
    - graph_lineage/data_classes/neo4j/nodes/experiment.py
    - graph_lineage/data_classes/neo4j/nodes/recipe.py
decisions:
  - "SHA-256 chosen for file hashing (standard, collision-resistant)"
  - "CRLF normalization applied before hashing for cross-platform consistency"
  - "Symlink/traversal/size protections added per threat model T-03-01 and T-03-03"
metrics:
  duration: "~5min"
  completed: "2026-05-08"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 17
  tests_passing: 17
---

# Phase 03 Plan 01: Snapshot and Differ Infrastructure Summary

SHA-256-hashed frozen CodebaseSnapshot with unified diff generation via difflib, plus Experiment model bug fixes and field renames to *_hash pattern.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Fix Experiment model bugs + field renames | 14c9ea3 | experiment.py, test_experiment_model.py |
| 2 | Create CodebaseSnapshot and Differ modules | 915d76a | snapshot.py, differ.py, __init__.py, test_snapshot.py, test_differ.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed recipe.py Field() dual-default bug**
- **Found during:** Task 1 (test collection)
- **Issue:** `recipe.py` line 38-39 had `Field([],default_factory=list)` which is invalid in Pydantic v2 (cannot specify both default and default_factory)
- **Fix:** Removed the positional `[]` default, kept only `default_factory=list`
- **Files modified:** graph_lineage/data_classes/neo4j/nodes/recipe.py
- **Commit:** 14c9ea3

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|-----------|
| T-03-01 (Tampering) | capture_snapshot uses Path.resolve(), rejects symlinks, validates relative_to root |
| T-03-03 (DoS) | MAX_FILE_SIZE=10MB check before reading any file |

## Verification Results

All 17 tests pass:
- 6 Experiment model tests
- 5 CodebaseSnapshot tests
- 6 Differ tests

## Self-Check: PASSED
