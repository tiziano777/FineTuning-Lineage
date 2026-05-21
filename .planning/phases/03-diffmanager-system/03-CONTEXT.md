# Phase 3: DiffManager System - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Source:** Discussion with developer

<domain>
## Phase Boundary

Implement the DiffManager system: codebase snapshotting, unified diff generation, hash-based change detection for critical files, auto-generated descriptions, and codebase reconstruction from lineage chain. Includes Neo4j schema changes to Experiment node and DerivedFrom edge.

</domain>

<decisions>
## Implementation Decisions

### Neo4j Schema Changes
- Experiment node field `codebase`: base experiment (base=True) stores full snapshot `dict[str, str]`; derived experiments (base=False) store only the unified diff patch relative to **direct parent**
- Add `base: bool` field to Experiment Neo4j node (already exists in ExperimentConfig)
- Rename fields: `config` → `config_hash`, `prepare` → `prepare_hash`, `train` → `train_hash`, `requirements` → `requirements_hash` — store SHA-256 hashes instead of full file content
- Fix existing bug: `from git import Optional` → `from typing import Optional` in experiment.py
- Fix existing bug: `codebase: dict = Field("")` → `codebase: dict = Field(default_factory=dict)`

### DerivedFrom Edge — Redundant Diff Storage
- DerivedFrom edge keeps `diff_patch: dict[str, Any]` — stores the same diff as the derived experiment's `codebase` field (redundancy by design)
- Enables querying diffs from both node and edge perspectives

### Diff Format
- Use **unified diff** format (Python `difflib.unified_diff`)
- Diff is relative to **direct parent** experiment (not base t_0)

### Hash-Based Change Detection
- 4 critical files: `config.yaml`, `prepare.py`, `train.py`, `requirements.txt`
- SHA-256 hash of each file stored in experiment node
- On new derived experiment: compare hashes to detect which critical files changed

### Auto-Generated Description Messages
- Configurable via `graph_lineage/config_file/commit_msg/lineage_messages.yml`
- Messages format: `"{filename} modified"` per changed critical file
- If multiple critical files changed: concatenate messages
- If no critical files changed: `"codebase changes, but not in critical files"`
- If no changes at all: `"no codebase changes"`
- RETRY strategy: `"RETRY FROM {exp_id}"`
- RESUME strategy: `"RESUME FROM {exp_id}, checkpoint {ckp_id}"`
- File is **bundled in package** with user override support (if user provides own YML, use that)

### Codebase Reconstruction
- Function to reconstruct codebase at any point t_n: walk DERIVED_FROM chain from base (t_0) to target, apply diffs in order
- Base experiment provides full snapshot, each intermediate experiment contributes its diff

### Critical Files List
- Hard-coded in YML config: `config.yaml`, `prepare.py`, `train.py`, `requirements.txt`
- Configurable later via the same YML file

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Neo4j Schema
- `docs/neo4j_schema.md` — Current schema definition (indexes on hash fields already defined)
- `graph_lineage/data_classes/neo4j/nodes/experiment.py` — Experiment node model (needs modification)
- `graph_lineage/data_classes/neo4j/nodes/base.py` — BaseEntity with UUID + timestamps
- `graph_lineage/data_classes/neo4j/edges/derived_from.py` — DerivedFrom edge model

### Config System (Phase 2 output)
- `graph_lineage/config_file/data_classes/experiment_config.py` — ExperimentConfig with base:bool field
- `graph_lineage/config_file/data_classes/lineage_config.py` — Root LineageConfig

### Architecture
- `docs/LINEAGE_SYSTEM_ARCHITECTURE.md` — System architecture overview

</canonical_refs>

<specifics>
## Specific Ideas

- DiffManager: `graph_lineage/diff/` package
- Snapshot: `graph_lineage/diff/snapshot.py` — CodebaseSnapshot class
- Differ: `graph_lineage/diff/differ.py` — unified diff generation + hash computation
- Reconstructor: `graph_lineage/diff/reconstructor.py` — rebuild codebase from lineage chain
- Messages config: `graph_lineage/config_file/commit_msg/lineage_messages.yml`
- Message loader: `graph_lineage/config_file/commit_msg/loader.py`

</specifics>

<deferred>
## Deferred Ideas

- RuleEngine (NEW/RETRY/BRANCH/RESUME/MERGE decision logic) — may fit Phase 4 with the hook decorator
- Commit message generation for git — out of scope, description is for Experiment.description field

</deferred>

---

*Phase: 03-diffmanager-system*
*Context gathered: 2026-05-08 via developer discussion*
