# diff/ Module — Codebase Diffing & Snapshots

## Overview

Captures project state (all files + content hashes), detects changes between states, generates human-readable descriptions, and can reconstruct prior states.

**Location:** `graph_lineage/diff/`

## Public API

```python
from graph_lineage.diff import (
    CodebaseSnapshot,
    capture_snapshot,              # -> CodebaseSnapshot
    compute_file_hash,
    compute_unified_diff,
    detect_changes,
    compute_snapshot_diff,         # -> (patch_dict, changed_files)
    generate_description,          # -> str (human-readable)
    apply_unified_diff,
    reconstruct_codebase,          # -> CodebaseSnapshot
)
```

## Components

### 1. `snapshot.py` — Capture & Represent Project State

**Purpose:** Scan project directory, capture all relevant files (with content hashes).

**Key Classes:**
- `CodebaseSnapshot` — Pydantic model
  ```python
  class CodebaseSnapshot(BaseModel):
      files: dict[str, str]  # {path: content} for all scanned files
      hashes: dict[str, str] # {path: sha256(content)}
  ```

**Key Functions:**
- `capture_snapshot(root_path: str) -> CodebaseSnapshot`

**Scan Rules:**
| Scope | Pattern | Example | Excluded |
|-------|---------|---------|----------|
| Root level | `*.py`, `*.txt`, `*.yml`, `*.yaml` | `train.py`, `config.yml` | `.env`, `.git/` |
| `modules/` | Recursive `*.py`, `*.yml`, `*.yaml` | `modules/utils/helper.py` | Hidden files |
| `.lineage/` | All files | `.lineage/experiment.yml` | N/A (always included) |
| File size | > 10MB → `FileTooLargeError` (exit code 8) | — | Blocks execution |

### 2. `differ.py` — Compute Diffs Between Snapshots

**Purpose:** Compare two snapshots, extract changed files, generate unified diffs.

**Key Functions:**
- `compute_file_hash(content: str) -> str` — SHA256 hash
- `compute_unified_diff(old_content, new_content) -> str` — Git-style unified diff
- `detect_changes(old_snapshot, new_snapshot) -> list[str]` — List of changed file paths
- `compute_snapshot_diff(old_snap, new_snap) -> dict[str, str]` — Diff for each changed file
  ```python
  {
    "train.py": "@@ -10,3 +10,5 @@\n+ new line\n...",
    "config.yml": "@@ -5,1 +5,2 @@\n..."
  }
  ```

### 3. `description.py` — Human-Readable Change Summary

**Purpose:** Generate narrative description of changes based on run strategy.

**Key Functions:**
- `generate_description(strategy: str, changed_files: list[str]) -> str`

**Output Examples:**
```
NEW: Base experiment. No prior state.
RETRY: Identical config & code. Same dependencies. Retrying with different seed.
BRANCH: Code changed (train.py, modules/utils.py). Config tuned. Derived from previous.
RESUME: Resuming from checkpoint. No code changes. Same config.
```

### 4. `reconstructor.py` — Rebuild Codebase from Base + Diffs

**Purpose:** Reconstruct the exact state of a prior experiment by applying a chain of diffs.

**Key Functions:**
- `apply_unified_diff(base_content: str, patch: str) -> str` — Apply single patch
- `reconstruct_codebase(base_snap: CodebaseSnapshot, diffs_chain: list[dict]) -> CodebaseSnapshot`

**Use Case:** "Show me the codebase state at experiment E-2026-05-15-002"

---

## Data Flow

```
Project Directory
       │
       ▼
capture_snapshot()
       │
       ├─ Scan root: *.py, *.txt, *.yml, *.yaml
       ├─ Scan modules/: recursive *.py, *.yml
       ├─ Scan .lineage/: all files
       ├─ Skip: .venv/, .cache/, .env, .git/, > 10MB files
       │
       ▼
CodebaseSnapshot(files={path: content}, hashes={path: hash})
       │
       ├──────────────┬──────────────┬──────────────┐
       │              │              │              │
       ▼              ▼              ▼              ▼
   Current      Parent Snap   Grandparent    Base (NEW)
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
              All used for comparison
              
       ▼
detect_changes(parent_snap, current_snap)
       │
       ├─ Compare hashes
       ├─ Identify changed files
       │
       ▼
compute_snapshot_diff()
       │
       ├─ For each changed file:
       │  ├─ compute_unified_diff(parent_content, current_content)
       │  └─ Store in patch dict
       │
       ▼
Patch Dict: {path: unified_diff}
       │
       ├─ Serialize to JSON → store in Neo4j DERIVED_FROM edge
       ├─ Extract changed_files list → store in Experiment node
       └─ Pass to generate_description()
              │
              ▼
         Human-readable summary
         (shown in UI + logs)
```

---

## Key Concepts

### Hash-Based Change Detection
- Each file gets SHA256 hash
- Compare parent_hash vs current_hash (O(1) per file)
- No need to diff every file—only changed ones get unified diff

### Unified Diff Format (Git-Style)
```
@@ -10,3 +10,5 @@
 unchanged line
-old line
+new line
+another new line
 another unchanged
```

### Reconstruction Example
```
Base codebase (NEW): C₀
  ↓ (apply diff from exp1)
Exp1 codebase: C₀ + ∆₁
  ↓ (apply diff from exp2)
Exp2 codebase: C₀ + ∆₁ + ∆₂
  ↓ (apply diff from exp3)
Exp3 codebase: C₀ + ∆₁ + ∆₂ + ∆₃

reconstruct_codebase(base=C₀, diffs=[∆₁, ∆₂, ∆₃]) → Exp3 codebase
```

---

## Integration

### In Rule Engine
```python
from graph_lineage.diff import CodebaseSnapshot, compute_snapshot_diff

current_snapshot = CodebaseSnapshot.capture(root_path)
parent_snapshot = ...  # from DB or file

result = compute_snapshot_diff(parent_snapshot, current_snapshot)
# result = (patch_dict, changed_files)

# If BRANCH: store patch_dict in Neo4j DERIVED_FROM edge
```

### In Server (Remote Mode)
```python
# Client captures snapshot
snapshot = capture_snapshot(project_root)

# Send to server
POST /api/v1/pre
  snapshot: {path: content}

# Server compares vs DB + generates diffs
```

### In History Navigation
```python
# Reconstruct exp-003 state
base_snap = get_base_experiment_snapshot()
diffs = get_diffs_chain(exp_003)
exp_003_state = reconstruct_codebase(base_snap, diffs)

# Show user what files existed at exp-003
```

---

## Exit Codes

| Code | Scenario | Resolution |
|------|----------|------------|
| 8 | `FileTooLargeError` — file > 10MB | Remove/compress file, or exclude from scan |

---

## Testing

**Location:** `tests/test_diff_*.py`

**Coverage:**
- Snapshot capture (scan rules, size limits)
- Hash computation
- Diff generation (unified format)
- Change detection (hash matching)
- Reconstruction (apply patches sequentially)

**Example:**
```python
def test_capture_snapshot_excludes_venv():
    snap = capture_snapshot(project_root)
    assert not any(".venv" in p for p in snap.files.keys())

def test_compute_snapshot_diff():
    old = CodebaseSnapshot(files={"train.py": "old code"}, ...)
    new = CodebaseSnapshot(files={"train.py": "new code"}, ...)
    patch, changed = compute_snapshot_diff(old, new)
    assert "train.py" in patch
    assert "- old code" in patch["train.py"]
    assert "+ new code" in patch["train.py"]

def test_reconstruct_codebase():
    base = CodebaseSnapshot(files={"file.py": "v1"})
    patch1 = {"file.py": "@@ -1 +1 @@\n- v1\n+ v2"}
    patch2 = {"file.py": "@@ -1 +1 @@\n- v2\n+ v3"}
    result = reconstruct_codebase(base, [patch1, patch2])
    assert result.files["file.py"] == "v3"
```

---

## Troubleshooting

### Q: "How do I exclude a file from snapshots?"
**A:** Edit `diff/snapshot.py` scan rules (EXCLUDED_PATTERNS). Currently excludes .venv/, .cache/, .env, .git/. To add custom: modify the scan logic.

### Q: "FileTooLargeError — what's the limit?"
**A:** 10MB per file. If your dataset/checkpoint is > 10MB, exclude it from scan (it won't be part of versioning anyway—only `.lineage/` + code should be tracked).

### Q: "How do I view the unified diff between two experiments?"
**A:** Query Neo4j for the DERIVED_FROM edge properties (includes diff_patch JSON), then deserialize. Or use Streamlit History page (reconstructs state on-demand).

---

## See Also

- [lineage.md](lineage.md) — How diffs are used in run type detection
- [history.md](history.md) — How diffs are used in reconstruction
- [neo4j_schema.md](../neo4j_schema.md) — DERIVED_FROM edge stores diff_patch

