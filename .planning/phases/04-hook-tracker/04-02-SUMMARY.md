---
phase: 04-hook-tracker
plan: 04-02
subsystem: observability
tags: [metrics, openlit, collector, gpu, jsonl]
dependency_graph:
  requires: [04-01]
  provides: [MetricsCollector, get_collector, get_gpu_stats]
  affects: [tracker.py, output_config.py, experiment.py, docker-compose.yml]
tech_stack:
  added: [openlit, pynvml]
  patterns: [dual-write, thread-local, K-step batching]
key_files:
  created:
    - graph_lineage/observability/__init__.py
    - graph_lineage/observability/collector.py
    - graph_lineage/observability/hw.py
    - tests/test_collector.py
  modified:
    - docker-compose.yml
    - graph_lineage/config_file/data_classes/output_config.py
    - graph_lineage/data_classes/neo4j/nodes/experiment.py
    - graph_lineage/lineage/tracker.py
    - pyproject.toml
decisions:
  - Replaced old opentelemetry observability deps with openlit + pynvml
  - Unified hw_metrics_uri into single metrics_uri field
metrics:
  duration: 148s
  completed: 2026-05-11
---

# Phase 04 Plan 02: Observability Layer (OpenLIT + Unified Metrics) Summary

**One-liner:** Thread-safe MetricsCollector with K-step batched dual-write to OpenLIT SDK + local JSONL, integrated into tracker lifecycle.

## What Was Done

### Wave 1: Infrastructure
- Added OpenLIT container service to `docker-compose.yml` (port 3000, persistent volume)
- Removed `hw_metrics_uri` from `OutputConfig` and `Experiment` node -- unified into single `metrics_uri`

### Wave 2: Collector Implementation
- Created `graph_lineage/observability/collector.py` with `MetricsCollector` class
  - Thread-safe buffering with `threading.Lock`
  - Flushes every K steps (configurable via `collect_every`)
  - Dual-write: OpenLIT SDK (best-effort) + local JSONL file
  - Graceful degradation when openlit not installed or unreachable
- Created `graph_lineage/observability/hw.py` with `get_gpu_stats()` via pynvml
- Created `graph_lineage/observability/__init__.py` exposing public API

### Wave 3: Integration with Tracker
- Extended `envelope.tracker()` with `collect_every` parameter
- `_pre_execution` instantiates `MetricsCollector` and stores via `set_collector()`
- `_post_execution` calls `collector.finalize()` to flush remaining buffer
- Added `collector` field to `ExecutionContext` dataclass
- Replaced old opentelemetry deps in pyproject.toml with `openlit>=1.0` and `pynvml>=11.0`

### Wave 4: Tests
- 12 unit tests covering buffering, K-step flush, JSONL format, finalize, graceful degradation, thread-local isolation
- All 30 tests pass (rule_engine + tracker + collector)

## Deviations from Plan

None - plan executed exactly as written.

## Commits

| Wave | Hash | Message |
|------|------|---------|
| 1 | 1fd2549 | feat(04-02): add OpenLIT service and unify metrics fields |
| 2 | d3aff6a | feat(04-02): implement MetricsCollector with dual-write and GPU stats |
| 3 | cd55bd8 | feat(04-02): integrate MetricsCollector into tracker lifecycle |
| 4 | eca7866 | test(04-02): add MetricsCollector unit tests |
