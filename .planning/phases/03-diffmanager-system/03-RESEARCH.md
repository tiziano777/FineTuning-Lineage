# Phase 3: DiffManager System - Research

**Researched:** 2026-05-08
**Domain:** Codebase snapshotting, unified diff generation, hash-based change detection, lineage chain reconstruction
**Confidence:** HIGH

## Summary

Phase 3 implements the DiffManager subsystem: a package under `graph_lineage/diff/` that captures codebase snapshots (4 critical files), computes SHA-256 hashes for change detection, generates unified diffs between experiment versions, auto-generates description messages from configurable YML, and reconstructs full codebase state from a lineage chain of diffs.

The phase also modifies the existing Experiment node model (rename 4 fields to `*_hash`, fix two bugs, add `base: bool`) and updates the DerivedFrom edge to carry redundant diff data. All tools needed are Python stdlib (`difflib`, `hashlib`, `pathlib`) plus PyYAML (already a project dependency). No new external dependencies are required.

**Primary recommendation:** Use only Python stdlib for diff/hash operations (`difflib.unified_diff` + `hashlib.sha256`). Structure `graph_lineage/diff/` as three focused modules (snapshot, differ, reconstructor) plus a separate message loader under `graph_lineage/config_file/commit_msg/`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Experiment node field `codebase`: base experiment (base=True) stores full snapshot `dict[str, str]`; derived experiments (base=False) store only the unified diff patch relative to direct parent
- Add `base: bool` field to Experiment Neo4j node (already exists in ExperimentConfig)
- Rename fields: `config` -> `config_hash`, `prepare` -> `prepare_hash`, `train` -> `train_hash`, `requirements` -> `requirements_hash` -- store SHA-256 hashes instead of full file content
- Fix existing bug: `from git import Optional` -> `from typing import Optional` in experiment.py
- Fix existing bug: `codebase: dict = Field("")` -> `codebase: dict = Field(default_factory=dict)`
- DerivedFrom edge keeps `diff_patch: dict[str, Any]` -- stores the same diff as the derived experiment's `codebase` field (redundancy by design)
- Use unified diff format (Python `difflib.unified_diff`)
- Diff is relative to direct parent experiment (not base t_0)
- 4 critical files: `config.yaml`, `prepare.py`, `train.py`, `requirements.txt`
- SHA-256 hash of each file stored in experiment node
- Auto-generated description messages configurable via `graph_lineage/config_file/commit_msg/lineage_messages.yml`
- Messages format: `"{filename} modified"` per changed critical file, concatenated if multiple, fallback messages for no-critical-change and no-change cases
- RETRY strategy: `"RETRY FROM {exp_id}"`
- RESUME strategy: `"RESUME FROM {exp_id}, checkpoint {ckp_id}"`
- Message file is bundled in package with user override support
- Codebase reconstruction: walk DERIVED_FROM chain from base (t_0) to target, apply diffs in order
- Critical files list hard-coded in YML config, configurable later

### Claude's Discretion
- Internal implementation details of each module (class APIs, method signatures)
- Error handling patterns within diff operations
- Test structure and fixture design

### Deferred Ideas (OUT OF SCOPE)
- RuleEngine (NEW/RETRY/BRANCH/RESUME/MERGE decision logic) -- may fit Phase 4 with the hook decorator
- Commit message generation for git -- out of scope, description is for Experiment.description field
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| R3.1 | CodeSnapshot -- serialize 4 critical files to JSON dict | snapshot.py module using pathlib + file I/O; dict[str, str] format |
| R3.2 | DiffAnalyzer / Differ -- compare snapshots, generate unified diff | differ.py using `difflib.unified_diff`; per-file diff stored as string |
| R3.2+ | Hash-based change detection for 4 critical files | `hashlib.sha256` per file; compare hashes to detect changes |
| R3.2+ | Auto-generated description messages | lineage_messages.yml with PyYAML loader; bundled via package_data |
| R3.2+ | Codebase reconstruction from lineage chain | reconstructor.py using `difflib` patch application or line-by-line rebuild |
| R3.2+ | Neo4j schema changes (Experiment node + DerivedFrom edge) | Pydantic model modifications; field renames + type changes |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Python 3.10+
- Pydantic v2 for all data models
- TDD development -- write tests first
- Object-oriented style, from abstraction to implementations
- Maximum modularity and extendability
- Every imported package/class/decorator must exist -- do not invent
- After every stage: test, update documentation, refactor check
- Use `.venv` in the project to run tests and commands

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| difflib (stdlib) | Python 3.10+ | Unified diff generation | Locked decision: `difflib.unified_diff` [VERIFIED: CONTEXT.md] |
| hashlib (stdlib) | Python 3.10+ | SHA-256 hash computation | Locked decision for change detection [VERIFIED: CONTEXT.md] |
| pathlib (stdlib) | Python 3.10+ | File path handling, reading critical files | Standard Python file I/O [VERIFIED: stdlib] |
| pydantic | 2.13.0 | Data models for Experiment, DerivedFrom | Project standard [VERIFIED: .venv pip] |
| pyyaml | 6.0.3 | Load/dump lineage_messages.yml config | Already in project deps [VERIFIED: .venv pip] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.0.3 | Unit testing | TDD for all diff modules [VERIFIED: .venv pip] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| difflib.unified_diff | diff-match-patch | LOCKED: user chose difflib. diff-match-patch is in pyproject.toml but NOT installed in venv; difflib is stdlib with zero deps |

**Installation:**
```bash
# No new packages needed -- all dependencies already in pyproject.toml / stdlib
```

## Architecture Patterns

### Recommended Project Structure
```
graph_lineage/
├── diff/                          # NEW package
│   ├── __init__.py                # Export public API
│   ├── snapshot.py                # CodebaseSnapshot class
│   ├── differ.py                  # Unified diff + hash computation
│   └── reconstructor.py           # Rebuild codebase from lineage chain
├── config_file/
│   ├── commit_msg/                # NEW subpackage
│   │   ├── __init__.py
│   │   ├── lineage_messages.yml   # Default message templates (bundled)
│   │   └── loader.py             # Load YML with user override support
│   └── data_classes/
│       └── experiment_config.py   # Already has base:bool
├── data_classes/
│   └── neo4j/
│       ├── nodes/
│       │   └── experiment.py      # MODIFY: rename fields, fix bugs, add base
│       └── edges/
│           └── derived_from.py    # Already has diff_patch: dict[str, Any]
```

### Pattern 1: CodebaseSnapshot as Immutable Value Object
**What:** A frozen Pydantic model that captures the state of 4 critical files at a point in time.
**When to use:** Every time the hook runs (pre-execution), to capture current codebase state.
**Example:**
```python
# Source: project convention (Pydantic v2 BaseModel)
from pydantic import BaseModel, Field
import hashlib

class CodebaseSnapshot(BaseModel):
    """Immutable snapshot of critical files at a point in time."""
    model_config = {"frozen": True}

    files: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of filename -> file content"
    )

    def file_hash(self, filename: str) -> str:
        """SHA-256 hash of a single file's content."""
        content = self.files.get(filename, "")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def hashes(self) -> dict[str, str]:
        """SHA-256 hashes for all files."""
        return {fname: self.file_hash(fname) for fname in self.files}
```

### Pattern 2: Differ with Unified Diff Output
**What:** Compares two CodebaseSnapshots and produces per-file unified diffs.
**When to use:** When creating a derived experiment to compute the diff stored in `codebase` field and `DerivedFrom.diff_patch`.
**Example:**
```python
# Source: Python stdlib difflib
import difflib

def compute_unified_diff(
    old_content: str,
    new_content: str,
    filename: str,
) -> str:
    """Generate unified diff between two file versions."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)
```

### Pattern 3: Lineage Chain Reconstruction
**What:** Walk the DERIVED_FROM chain from base to target, applying diffs sequentially.
**When to use:** When user needs to reconstruct full codebase at experiment t_n.
**Example:**
```python
# Source: project architecture decision
def reconstruct_codebase(chain: list[dict]) -> dict[str, str]:
    """
    chain[0] = base experiment (full snapshot in codebase field)
    chain[1..n] = derived experiments (unified diffs in codebase field)
    """
    # Start with base snapshot
    current_files = dict(chain[0]["codebase"])

    for experiment in chain[1:]:
        diffs = experiment["codebase"]  # dict[str, str] of filename -> unified_diff
        for filename, patch in diffs.items():
            if filename in current_files:
                current_files[filename] = apply_unified_diff(
                    current_files[filename], patch
                )
            else:
                # New file added
                current_files[filename] = extract_new_content(patch)

    return current_files
```

### Pattern 4: YML Message Loader with User Override
**What:** Load message templates from bundled YML, allow user to override with their own file.
**When to use:** When generating experiment description messages.
**Example:**
```python
# Source: project decision -- bundled in package with user override
from pathlib import Path
import yaml

_DEFAULT_PATH = Path(__file__).parent / "lineage_messages.yml"

def load_messages(user_path: Path | None = None) -> dict[str, str]:
    """Load message templates. User file overrides bundled defaults."""
    path = user_path if user_path and user_path.exists() else _DEFAULT_PATH
    with open(path) as f:
        return yaml.safe_load(f)
```

### Anti-Patterns to Avoid
- **Storing full file content in hash fields:** The decision is to store SHA-256 hashes, not content. The old fields stored full text -- the rename signals the semantic change.
- **Computing diff against base t_0:** Diffs are relative to the DIRECT PARENT, not the base experiment. This is critical for correct reconstruction.
- **Mutable snapshot objects:** Snapshots should be immutable (frozen) to prevent accidental modification after capture.
- **Hardcoding message strings:** Messages must come from the YML config file, not be hardcoded in Python.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unified diff generation | Custom line-by-line comparison | `difflib.unified_diff` | Handles edge cases (no newline at EOF, binary detection, context lines) [VERIFIED: stdlib docs] |
| SHA-256 hashing | Custom hash function | `hashlib.sha256` | Cryptographic correctness, C-optimized performance [VERIFIED: stdlib] |
| YAML parsing | Custom parser | `pyyaml` (yaml.safe_load/dump) | Already a project dependency, handles all YAML edge cases [VERIFIED: pyproject.toml] |
| Path manipulation | String concatenation | `pathlib.Path` | Cross-platform, safe path joining [VERIFIED: stdlib] |

**Key insight:** This phase is almost entirely stdlib-based. The complexity is in the data flow and schema design, not in external tooling.

## Common Pitfalls

### Pitfall 1: Applying Unified Diffs Programmatically
**What goes wrong:** Python's `difflib` generates unified diffs but does NOT provide a built-in `patch` function to apply them back. `difflib.unified_diff` is output-only.
**Why it happens:** Developers assume if you can generate a diff, the same library can apply it.
**How to avoid:** For reconstruction, either (a) parse the unified diff manually to extract hunks and apply line changes, or (b) store the new file content alongside the diff, or (c) use a small patch-application utility. The simplest reliable approach is to write a `apply_unified_diff()` function that parses the unified diff format (@@-lines for hunk headers, +/- for additions/removals).
**Warning signs:** Tests pass for diff generation but fail on reconstruction.

### Pitfall 2: Encoding Issues in File Content
**What goes wrong:** SHA-256 hashes differ between machines due to line ending differences (CRLF vs LF) or encoding mismatches.
**Why it happens:** Reading files in text mode on different OSes produces different line endings.
**How to avoid:** Normalize line endings before hashing: `content.replace('\r\n', '\n')`. Always use UTF-8 encoding explicitly.
**Warning signs:** Hash comparison fails for identical logical content.

### Pitfall 3: Empty or Missing Critical Files
**What goes wrong:** Snapshot fails or produces incorrect hashes when a critical file does not exist in the codebase.
**Why it happens:** Not all codebases have all 4 critical files (e.g., no `prepare.py`).
**How to avoid:** Handle missing files gracefully -- store empty string or skip the file. Hash of empty string is a known constant. Document this behavior.
**Warning signs:** KeyError on snapshot access, or incorrect "no changes" detection when a file is newly added.

### Pitfall 4: Circular or Broken Lineage Chains
**What goes wrong:** Reconstruction enters infinite loop or fails with missing parent.
**Why it happens:** Data corruption or manual DB edits break the DERIVED_FROM chain.
**How to avoid:** Add max depth guard (e.g., 100 levels). Validate chain integrity before reconstruction (every non-base experiment must have exactly one DERIVED_FROM edge to its parent).
**Warning signs:** Reconstruction hangs or returns partial results.

### Pitfall 5: YML File Not Bundled in Package Distribution
**What goes wrong:** `lineage_messages.yml` not found at runtime after `pip install`.
**Why it happens:** By default, Python packaging does not include non-`.py` files.
**How to avoid:** Add the YML path to `pyproject.toml` under `[tool.hatch.build.targets.wheel]` with `artifacts` or use `package-data` in hatchling config. Alternatively, use `importlib.resources` for reliable resource access.
**Warning signs:** FileNotFoundError in production but works in development.

### Pitfall 6: Diff Dict Structure Mismatch Between Node and Edge
**What goes wrong:** The `codebase` field on Experiment and `diff_patch` on DerivedFrom edge get out of sync.
**Why it happens:** Writing to node and edge in separate operations without transactional guarantee.
**How to avoid:** Compute the diff dict once, pass the same object to both the Experiment.codebase setter and DerivedFrom.diff_patch setter. Document the redundancy contract clearly.
**Warning signs:** Querying diff from node gives different result than querying from edge.

## Code Examples

### Snapshot Capture from Filesystem
```python
# Source: project convention + pathlib stdlib
from pathlib import Path

CRITICAL_FILES = ["config.yaml", "prepare.py", "train.py", "requirements.txt"]

def capture_snapshot(codebase_root: Path) -> CodebaseSnapshot:
    """Read critical files from disk into a snapshot."""
    files: dict[str, str] = {}
    for filename in CRITICAL_FILES:
        filepath = codebase_root / filename
        if filepath.exists():
            files[filename] = filepath.read_text(encoding="utf-8")
        else:
            files[filename] = ""  # Missing file = empty content
    return CodebaseSnapshot(files=files)
```

### Hash Comparison for Change Detection
```python
# Source: project decision (SHA-256 per critical file)
import hashlib

def compute_file_hash(content: str) -> str:
    """SHA-256 hash of file content, normalized for cross-platform consistency."""
    normalized = content.replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def detect_changes(
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
) -> list[str]:
    """Return list of filenames whose hash changed."""
    changed = []
    all_files = set(old_hashes) | set(new_hashes)
    for filename in all_files:
        if old_hashes.get(filename) != new_hashes.get(filename):
            changed.append(filename)
    return changed
```

### Description Message Generation
```python
# Source: project decision (lineage_messages.yml templates)
def generate_description(
    changed_files: list[str],
    strategy: str,
    messages: dict[str, str],
    exp_id: str | None = None,
    ckp_id: str | None = None,
) -> str:
    """Auto-generate experiment description from changes and strategy."""
    if strategy == "RETRY":
        return messages["retry"].format(exp_id=exp_id)
    if strategy == "RESUME":
        return messages["resume"].format(exp_id=exp_id, ckp_id=ckp_id)
    if not changed_files:
        return messages["no_changes"]
    critical = [f for f in changed_files if f in CRITICAL_FILES]
    if not critical:
        return messages["non_critical_changes"]
    parts = [messages["file_modified"].format(filename=f) for f in critical]
    return ", ".join(parts)
```

### lineage_messages.yml Structure
```yaml
# Source: project decision
file_modified: "{filename} modified"
no_changes: "no codebase changes"
non_critical_changes: "codebase changes, but not in critical files"
retry: "RETRY FROM {exp_id}"
resume: "RESUME FROM {exp_id}, checkpoint {ckp_id}"

# Critical files list (configurable)
critical_files:
  - config.yaml
  - prepare.py
  - train.py
  - requirements.txt
```

### Experiment Node Model (After Modifications)
```python
# Source: existing experiment.py with CONTEXT.md changes applied
from __future__ import annotations
from typing import Optional
from pydantic import Field
from .base import BaseEntity

class Experiment(BaseEntity):
    description: Optional[str] = Field("", description="Experiment description")
    uri: str = Field("", description="Path scaffold on worker")
    base: bool = Field(True, description="True for base experiment, False for derived")

    status: Optional[str] = Field("RUNNING", description="RUNNING | COMPLETED | FAILED | PAUSED")
    exit_status: Optional[str] = None
    exit_msg: Optional[str] = None
    strategy: str = Field("", description="NEW | RESUME | BRANCH | RETRY")

    # base=True: full snapshot dict[str, str]; base=False: unified diff dict
    codebase: dict = Field(default_factory=dict, description="Snapshot or diff of codebase")
    # SHA-256 hashes of critical files (renamed from content fields)
    config_hash: str = Field("", description="SHA-256 of config.yaml")
    prepare_hash: str = Field("", description="SHA-256 of prepare.py")
    train_hash: str = Field("", description="SHA-256 of train.py")
    requirements_hash: str = Field("", description="SHA-256 of requirements.txt")

    usable: bool = Field(True, description="Is experiment usable")
    manual_save: bool = Field(False, description="Manually saved")
    metrics_uri: str = Field("", description="Pointer to training metrics")
    hw_metrics_uri: str = Field("", description="Pointer to hardware metrics")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Store full file content in Experiment node | Store SHA-256 hashes + diff-based codebase | Phase 3 (this phase) | Dramatically reduces Neo4j storage; enables efficient change detection |
| diff-match-patch library (originally planned) | difflib.unified_diff (stdlib) | CONTEXT.md decision | Zero external dependency for diff; simpler, well-understood format |
| Full codebase on every experiment | Base stores full, derived stores only diff | Phase 3 (this phase) | Solves "Experimental Explosion" problem (section 5.8 of architecture doc) |

**Deprecated/outdated:**
- `config`, `prepare`, `train`, `requirements` fields on Experiment: renamed to `*_hash` variants storing SHA-256 instead of content
- `from git import Optional`: bug, must be `from typing import Optional`
- `codebase: dict = Field("")`: bug, must use `default_factory=dict`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `importlib.resources` is the best way to access bundled YML in installed packages | Architecture Patterns (Pattern 4) | [ASSUMED] -- fallback is `Path(__file__).parent` which works for dev but may break in editable installs or zipped packages. Low risk since `Path(__file__).parent` works for the current hatchling wheel build. |
| A2 | Unified diff parsing for reconstruction can be implemented in ~50 lines of Python | Common Pitfalls (Pitfall 1) | [ASSUMED] -- if format proves complex, could use the `patch` CLI or a small library. Medium risk for correctness on edge cases. |
| A3 | Neo4j schema indexes (`idx_exp_config_hash`, `idx_exp_code_hash`, `idx_exp_req_hash`) already cover the renamed hash fields | Standard Stack | [ASSUMED] -- the neo4j_schema.md shows indexes on `config_hash`, `code_hash`, `req_hash` but the rename adds `prepare_hash` and `train_hash` separately. May need new indexes or the existing ones may need updating. |

## Open Questions (RESOLVED)

1. **Neo4j Index Alignment with Renamed Fields** (RESOLVED)
   - What we know: Current schema has indexes on `config_hash`, `code_hash`, `req_hash`. The CONTEXT.md renames to `config_hash`, `prepare_hash`, `train_hash`, `requirements_hash`.
   - Resolution: `code_hash` was a composite — it is dropped in favor of individual file hashes (`config_hash`, `prepare_hash`, `train_hash`, `requirements_hash`). Old indexes (`idx_exp_code_hash`, `idx_exp_req_hash`) are obsolete. New indexes for the 4 individual hash fields will be created in a migration step (deferred to Phase 5 integration, not Phase 3 scope — Phase 3 only modifies Pydantic models, not Neo4j DDL).

2. **Unified Diff Application for Reconstruction** (RESOLVED)
   - Resolution: `apply_unified_diff()` is implemented in Plan 02 Task 2 (`reconstructor.py`). Round-trip test verifies correctness.

3. **Codebase Field Type Polymorphism** (RESOLVED)
   - Resolution: Keep simple `dict[str, str]` with `base: bool` as discriminator. Plan 01 Task 1 adds docstring clarifying dual semantics (full snapshot vs diff patch).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `.venv/bin/pytest tests/test_diff*.py -x` |
| Full suite command | `.venv/bin/pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| R3.1 | Snapshot captures 4 critical files | unit | `.venv/bin/pytest tests/test_snapshot.py -x` | No -- Wave 0 |
| R3.1 | Missing file handled gracefully | unit | `.venv/bin/pytest tests/test_snapshot.py::test_missing_file -x` | No -- Wave 0 |
| R3.2 | Unified diff generated correctly | unit | `.venv/bin/pytest tests/test_differ.py -x` | No -- Wave 0 |
| R3.2 | Hash comparison detects changes | unit | `.venv/bin/pytest tests/test_differ.py::test_hash_changes -x` | No -- Wave 0 |
| R3.2+ | Description message generated | unit | `.venv/bin/pytest tests/test_messages.py -x` | No -- Wave 0 |
| R3.2+ | YML loader with user override | unit | `.venv/bin/pytest tests/test_messages.py::test_user_override -x` | No -- Wave 0 |
| R3.2+ | Codebase reconstruction round-trip | unit | `.venv/bin/pytest tests/test_reconstructor.py -x` | No -- Wave 0 |
| R3.2+ | Experiment model field renames | unit | `.venv/bin/pytest tests/test_experiment_model.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/test_diff*.py tests/test_snapshot.py tests/test_messages.py tests/test_reconstructor.py -x`
- **Per wave merge:** `.venv/bin/pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_snapshot.py` -- covers R3.1 (snapshot capture, missing files, binary skip)
- [ ] `tests/test_differ.py` -- covers R3.2 (diff generation, hash computation, change detection)
- [ ] `tests/test_messages.py` -- covers description message generation and YML loading
- [ ] `tests/test_reconstructor.py` -- covers codebase reconstruction round-trip
- [ ] `tests/test_experiment_model.py` -- covers Experiment model field renames and bug fixes

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All modules | Yes | 3.10+ (venv) | -- |
| difflib (stdlib) | Diff generation | Yes | stdlib | -- |
| hashlib (stdlib) | Hash computation | Yes | stdlib | -- |
| pathlib (stdlib) | File I/O | Yes | stdlib | -- |
| pydantic | Data models | Yes | 2.13.0 | -- |
| pyyaml | YML config loader | Yes | 6.0.3 | -- |
| pytest | Testing | Yes | 9.0.3 | -- |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `diff-match-patch` is listed in pyproject.toml but NOT installed in venv. Not needed -- using stdlib `difflib` per locked decision.

## Sources

### Primary (HIGH confidence)
- `graph_lineage/data_classes/neo4j/nodes/experiment.py` -- current Experiment model with bugs identified [VERIFIED: file read]
- `graph_lineage/data_classes/neo4j/edges/derived_from.py` -- DerivedFrom edge model [VERIFIED: file read]
- `graph_lineage/config_file/data_classes/experiment_config.py` -- ExperimentConfig with `base: bool` field [VERIFIED: file read]
- `docs/neo4j_schema.md` -- Current schema with indexes and constraints [VERIFIED: file read]
- `docs/LINEAGE_SYSTEM_ARCHITECTURE.md` -- Architecture decisions, section 5.8 Experimental Explosion [VERIFIED: file read]
- `.planning/phases/03-diffmanager-system/03-CONTEXT.md` -- Locked decisions from user [VERIFIED: file read]
- Python stdlib docs for difflib, hashlib [VERIFIED: runtime test in .venv]
- `pyproject.toml` -- Project dependencies and build config [VERIFIED: file read]

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` -- R3.x requirements [VERIFIED: file read]
- `.planning/ROADMAP.md` -- Phase scope and dependencies [VERIFIED: file read]

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all stdlib + already-installed deps, verified in venv
- Architecture: HIGH -- follows existing project patterns (Pydantic v2, package structure), locked by CONTEXT.md
- Pitfalls: HIGH -- pitfalls derived from verified stdlib behavior (difflib has no apply, encoding issues are well-documented)

**Research date:** 2026-05-08
**Valid until:** 2026-06-08 (stable -- all stdlib, no fast-moving deps)
