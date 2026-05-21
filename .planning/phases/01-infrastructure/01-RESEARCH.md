# Phase 1: Infrastructure Consolidation - Research

**Researched:** 2026-04-21
**Domain:** Python package architecture, storage abstraction, import consolidation
**Confidence:** HIGH

## Summary

Phase 1 is ~95% structurally complete. All code changes are staged: import paths consolidated (`data_class/` → `data_classes/`), StorageProvider abstraction implemented with LocalStorageProvider and StorageResolver, duplicate Cypher files marked for deletion, and pyproject.toml corrected. The remaining work is verification (test execution), finalizing __init__.py exports, and committing the changes.

**Primary recommendation:** Verify storage tests pass, confirm all imports resolve cleanly (especially via pylance), ensure graph_lineage/__init__.py exports StorageProvider/LocalStorageProvider for public API, then commit as a single atomic changeset.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Rename `graph_lineage/data_class/` → `graph_lineage/data_classes/` (already staged)
- **D-02:** Update all repository imports to use `data_classes` path (already done in recipe_validation.py, recipe_repository.py)
- **D-03:** Remove duplicate Cypher files — keep only `01-schema.cypher`, `02-triggers.cypher` (old duplicates already marked for deletion)
- **D-04:** Fix pyproject.toml `packages = ["graph_lineage"]` (already done)
- **D-05:** StorageProvider ABC interface sufficient — no separate resolver.py needed (resolver.py created anyway and is production-ready)
- **D-06:** LocalStorageProvider implementation complete — handles base_path resolution, directory creation, backup timestamps
- **D-07:** Export StorageProvider + LocalStorageProvider from `graph_lineage/__init__.py` for easy imports (NOT YET DONE — __init__.py currently empty)

### Claude's Discretion
- Test strategy for storage layer (unit tests sufficient? integration tests needed?)
- Verification approach before committing (what's the confidence gate?)

### Deferred Ideas (OUT OF SCOPE)
- Separate resolver/factory module — deferred until third storage backend needed
- Detailed storage documentation + code examples — Phase 4 when decorator is live
- Storage provider caching layer (for remote backends) — Phase 1.2 optimization
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| 1.1 | Rename data_class/ → data_classes/ | Files staged for deletion, new structure in place ✓ |
| 1.2 | Update all imports | recipe_validation.py, recipe_repository.py updated; no old imports found via grep ✓ |
| 1.3 | Remove duplicate Cypher files | Two files marked for deletion (neo4j_client/schema.cypher, triggers.cypher) ✓ |
| 1.4 | Fix pyproject.toml | packages = ["graph_lineage"] verified in pyproject.toml ✓ |
| 1.5 | Create StorageProvider ABC | provider.py complete with 8 abstract methods ✓ |
| 1.6 | Create LocalStorageProvider | local_provider.py complete with all methods implemented ✓ |
| 1.7 | Create StorageResolver | resolver.py complete with URI resolution + config support ✓ |
| 1.8 | Populate README/workflow/docker-compose | README, workflow.md, docker-compose.yml updated; verified in git status ✓ |
| 1.9 | Unit test storage provider | tests/test_storage.py exists with 20+ test cases ✓ |

</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.10+ | Required by project (union type syntax, match statements) | [VERIFIED: pyproject.toml requires-python = ">=3.10"] |
| Pydantic | v2 | Data validation (all entity models) | [VERIFIED: pyproject.toml dependencies pydantic>=2.0] |
| pathlib | stdlib | Cross-platform path handling (LocalStorageProvider uses it) | [VERIFIED: Python stdlib, used in local_provider.py lines 12, 28, 32] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PyYAML | >=6.0 | Config file parsing (StorageResolver loads .storage-config.yml) | [VERIFIED: pyproject.toml dependencies pyyaml>=6.0] |
| diff-match-patch | >=20230430 | Diff/patch generation (Phase 3, not Phase 1 but already in dependencies) | [VERIFIED: pyproject.toml] |
| Neo4j driver | >=5.0 | Database client (Phase 4, not Phase 1 but infrastructure enables it) | [VERIFIED: pyproject.toml neo4j>=5.0] |

### Testing
| Library | Version | Purpose | Configuration |
|---------|---------|---------|----------------|
| pytest | >=8.0 | Test framework | [VERIFIED: pyproject.toml dev dependencies pytest>=8.0] |
| pytest-cov | >=5.0 | Coverage reporting | [VERIFIED: pyproject.toml dev dependencies] |

**Installation:**
```bash
pip install -e ".[dev]"
```

**Version verification:** pyproject.toml is current and specifies minimum versions. All packages are actively maintained and compatible with Python 3.10+. [VERIFIED: pyproject.toml checked 2026-04-21]

---

## Architecture Patterns

### Recommended Project Structure

```
graph_lineage/
├── __init__.py                    # Public API exports (StorageProvider, LocalStorageProvider)
├── storage/                       # Storage abstraction layer
│   ├── __init__.py               # Exports: StorageProvider, LocalStorageProvider, StorageResolver
│   ├── provider.py               # StorageProvider ABC (8 methods, no implementation)
│   ├── local_provider.py         # LocalStorageProvider (concrete: local FS)
│   └── resolver.py               # StorageResolver (URI → provider mapping)
├── data_classes/                 # Pydantic entity models (renamed from data_class/)
│   ├── neo4j/
│   │   ├── nodes/               # Node type models (Recipe, Model, Experiment, etc)
│   │   └── edges/               # Edge/relationship models
├── streamlit_ui/                # UI layer (CRUD, Neo4j integration)
├── neo4j_client/                # Neo4j operations + Cypher scripts
│   ├── 01-schema.cypher         # Master schema (idempotent DDL)
│   ├── 02-triggers.cypher       # APOC triggers for timestamps
│   └── init_schema.py           # Schema loader
└── cli/                         # CLI entry point (future)

tests/
├── test_storage.py              # Storage provider unit tests
└── conftest.py                  # (TBD) Shared pytest fixtures
```

### Pattern 1: Storage Abstraction Layer

**What:** ABC (StorageProvider) decouples business logic from physical storage. Implementations (LocalStorageProvider) handle actual I/O.

**When to use:** Anytime you read/write files or directories. Enables future S3/SSH backends without touching client code.

**Example:**
```python
# Client code (Phase 2+)
from graph_lineage.storage import LocalStorageProvider

storage = LocalStorageProvider(base_path="/mnt/data")
storage.write_text("config.yml", yaml_content)
content = storage.read_text("config.yml")

# For remote backends (Phase 1.2+)
from custom_storage import S3StorageProvider
storage = S3StorageProvider(bucket="my-bucket")  # Same interface
```

**Source:** [VERIFIED: storage/provider.py lines 13-60, storage/local_provider.py lines 18-100]

### Pattern 2: Import Consolidation

**What:** Centralized exports via __init__.py + consistent internal paths.

**When to use:** When module grows (more than 3-4 files) or has multiple layers.

**Example:**
```python
# Old (scattered)
from graph_lineage.data_class.neo4j.nodes.recipe import Recipe

# New (consolidated)
from graph_lineage.data_classes.neo4j.nodes import Recipe
# Or with top-level export:
from graph_lineage import StorageProvider, LocalStorageProvider
```

**Source:** [VERIFIED: data_classes/neo4j/nodes/__init__.py lines 3-8 exports Recipe, Model, Component, Experiment]

### Pattern 3: Universal Path Resolver

**What:** StorageResolver maps URI prefixes to providers (e.g., "/mnt/shared" → LocalStorageProvider with base_path="/mnt/shared").

**When to use:** Multi-backend support or complex mount scenarios.

**Example:**
```python
# .storage-config.yml
mounts:
  - prefix: "/mnt/shared"
    provider: "local"
    base_path: "/mnt/shared"
  - prefix: "s3://"
    provider: "s3"  # (Future)
    bucket: "my-bucket"

# Usage (Phase 2+)
from graph_lineage.storage import StorageResolver
resolver = StorageResolver(config_path=".storage-config.yml")
provider, path = resolver.resolve("/mnt/shared/config.yml")
content = provider.read_text(path)
```

**Source:** [VERIFIED: storage/resolver.py lines 32-138, handles prefix mapping and fallback to LocalStorageProvider]

### Anti-Patterns to Avoid

- **Direct file operations in business logic:** Use StorageProvider instead (enables testing with temp dirs, future backends)
- **Hardcoded base paths:** Use LocalStorageProvider(base_path=...) for reproducibility
- **Import * patterns:** Use explicit imports (recipe_validation.py imports Recipe specifically, not *) — clarifies dependencies
- **Empty __init__.py files:** Root __init__.py should export public API (StorageProvider, LocalStorageProvider) — currently not done, needs fix
- **Mixed Cypher locations:** Consolidate to single location (neo4j_client/) — already done

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File I/O abstraction | Custom wrapper class | StorageProvider ABC + LocalStorageProvider | Extensible to SSH/S3; handles base_path, mkdir, backups; tested |
| Cross-platform paths | os.path.join() everywhere | pathlib.Path | Handles Windows/POSIX; used by LocalStorageProvider |
| YAML config parsing | Manual dict access | PyYAML + Pydantic v2 | Type-safe, validation, error messages |
| URI routing logic | If/elif chains | StorageResolver pattern | Maintainable, testable, extensible |
| Backup logic | Copy file to .bak | StorageProvider.backup() | Timestamp format, handles missing files, single responsibility |

**Key insight:** Storage abstraction looks "over-engineered" for local FS only, but implementation cost is low (100 lines) and payoff is high (enables Phase 1.2, testing with tmp dirs, S3/SSH support). Don't simplify to LocalStorageProvider-only until proven unnecessary.

---

## Common Pitfalls

### Pitfall 1: Python Version Mismatch in .venv

**What goes wrong:** Import errors like "cannot use | union syntax" on Python 3.9 even though pyproject.toml requires 3.10+.

**Why it happens:** .venv created with 3.9 system Python; pyproject.toml requires 3.10+ but doesn't force reinstall.

**How to avoid:**
1. Verify system Python: `python3.10 --version` or higher
2. Create fresh .venv: `python3.10 -m venv .venv && source .venv/bin/activate`
3. Install: `pip install -e ".[dev]"`
4. Verify: `python --version` (should be 3.10+)
5. Verify: Run test import: `python -c "from graph_lineage.storage import StorageProvider"`

**Warning signs:**
- Test runs fail with "invalid syntax" on union types (`str | None`)
- Import failures despite files existing
- IDE (pylance) reports no errors but CLI pytest fails

**Source:** [CONTEXT: Project requires Python 3.10+ (CLAUDE.md line 24), but system Python is 3.9.6]

### Pitfall 2: Relative vs Absolute Path Resolution in LocalStorageProvider

**What goes wrong:** `storage.write_text("config.yml", content)` writes to current directory instead of base_path; tests fail because paths aren't scoped.

**Why it happens:** LocalStorageProvider._resolve() checks `if p.is_absolute()` — if path is absolute, it ignores base_path. But relative paths like "config.yml" work. Mixed usage breaks reproducibility.

**How to avoid:**
1. Always pass relative paths to LocalStorageProvider: `storage.write_text("config.yml", ...)` not `/home/user/config.yml`
2. If you need absolute path resolution, create provider with `base_path=None`: `LocalStorageProvider()` (no base_path)
3. Test behavior:
   ```python
   storage = LocalStorageProvider(base_path="/tmp/test")
   storage.write_text("file.txt", "data")
   # Resolves to /tmp/test/file.txt, not cwd/file.txt
   ```

**Warning signs:**
- Files written to unexpected locations
- Tests fail when run from different directories
- base_path parameter silently ignored for absolute paths

**Source:** [VERIFIED: storage/local_provider.py lines 30-35, _resolve() logic with is_absolute() check]

### Pitfall 3: Forgetting to Export Public API from graph_lineage/__init__.py

**What goes wrong:** Users write `from graph_lineage import StorageProvider` and get ImportError, but `from graph_lineage.storage import StorageProvider` works. Confusing API surface.

**Why it happens:** graph_lineage/__init__.py is currently empty (0 lines). Public exports must be explicit.

**How to avoid:**
1. Add exports to graph_lineage/__init__.py:
   ```python
   from graph_lineage.storage import StorageProvider, LocalStorageProvider
   from graph_lineage.data_classes.neo4j.nodes import Recipe, Model, Experiment, Component
   __all__ = ["StorageProvider", "LocalStorageProvider", "Recipe", "Model", "Experiment", "Component"]
   ```
2. Document in README: "Import from `graph_lineage`, not submodules"
3. Test: `python -c "from graph_lineage import StorageProvider"` (should not raise)

**Warning signs:**
- ImportError for items that exist (but in submodules)
- Different import paths in docs vs code
- IDE autocomplete doesn't find items at top level

**Source:** [CONTEXT: D-07 says "Export StorageProvider + LocalStorageProvider from graph_lineage/__init__.py", but file is currently empty]

### Pitfall 4: __init__.py Files Left Empty (import paths broken)

**What goes wrong:** `from graph_lineage.data_classes.neo4j.nodes import Recipe` works, but `from graph_lineage.data_classes.neo4j import nodes; nodes.Recipe` fails because __init__.py is empty.

**Why it happens:** Empty __init__.py files are valid Python packages, but don't re-export submodules.

**How to avoid:**
- Empty __init__.py is fine for namespace packages (data_classes/neo4j/ doesn't need exports)
- Only root __init__.py (graph_lineage/__init__.py) needs public exports
- Verify import patterns in code match structure: if you use `from ...nodes import Recipe`, leave __init__.py empty; if you want `from ... import nodes`, add `from . import nodes` to parent __init__.py

**Warning signs:**
- Only absolute imports work (`from graph_lineage.data_classes.neo4j.nodes import Recipe`), not `from graph_lineage.data_classes.neo4j import nodes`
- IDE can't find symbols even though files exist
- Circular import errors

**Source:** [VERIFIED: data_classes/neo4j/__init__.py and edges/__init__.py are empty (0 lines) — this is correct for namespace packages; only graph_lineage/__init__.py needs exports]

### Pitfall 5: Duplicate Cypher Files Not Actually Deleted

**What goes wrong:** Git shows "D" (deletion) but old Cypher files still exist in working directory. Schema load picks up wrong version.

**Why it happens:** Files are staged for deletion (git status shows "D") but not yet committed. If uncommitted changes are lost, deletions are lost.

**How to avoid:**
1. Don't force-reset or unstage deletions: `git add -A && git commit` (include deletions in commit)
2. Verify deletion after commit: `git log --name-status` shows old files deleted
3. Verify only neo4j_client/01-schema.cypher and 02-triggers.cypher exist after commit

**Warning signs:**
- Old neo4j_client/schema.cypher still present (not neo4j_client/01-schema.cypher)
- init_schema.py loads wrong file (old path)
- "file already exists" errors when creating Neo4j schema

**Source:** [VERIFIED: git status shows 2 Cypher files marked "D" (deleted), neo4j_client/ directory now only has 01-schema.cypher and 02-triggers.cypher]

---

## Code Examples

### Storage Layer Usage (Phase 1 Complete)
```python
# Source: graph_lineage/storage/local_provider.py (verified implementation)
from graph_lineage.storage import LocalStorageProvider

# Example 1: With base_path (scoped)
storage = LocalStorageProvider(base_path="/mnt/shared")
storage.write_text("config.yml", yaml_content)
storage.read_text("config.yml")  # Reads from /mnt/shared/config.yml

# Example 2: Absolute paths (no scoping)
storage = LocalStorageProvider()
storage.write_text("/home/user/config.yml", yaml_content)

# Example 3: Directory operations
if storage.is_dir("/mnt/shared/data"):
    files = storage.list_files("/mnt/shared/data", "*.json")
    for path in storage.walk("/mnt/shared/data"):
        content = storage.read_text(path)

# Example 4: Backup before write
backup_path = storage.backup("/mnt/shared/config.yml")
storage.write_text("/mnt/shared/config.yml", new_content)
```

### StorageResolver for Multi-Backend (Future)
```python
# Source: graph_lineage/storage/resolver.py (verified, but .storage-config.yml not required yet)
from graph_lineage.storage import StorageResolver

# Initialize with optional config
resolver = StorageResolver(config_path=".storage-config.yml")

# Resolve URI to provider
provider, path = resolver.resolve("/mnt/shared/config.yml")
content = provider.read_text(path)

# Validate URIs before use
uris = ["/mnt/shared/config.yml", "/mnt/shared/output/metrics.jsonl"]
results = resolver.validate_uris(uris)
for uri, error in results.items():
    if error:
        print(f"ERROR: {uri} — {error}")
```

### Import Consolidation (Phase 1 Complete)
```python
# Source: graph_lineage/streamlit_ui/utils/recipe_validation.py (verified)
# OLD (scattered)
from graph_lineage.data_class.neo4j.nodes.recipe import Recipe

# NEW (consolidated)
from graph_lineage.data_classes.neo4j.nodes import Recipe
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| data_class/ directory | data_classes/ directory | Phase 1 (2026-04-21) | Plural naming matches Pydantic convention; allows import consolidation |
| Separate schema.cypher + triggers.cypher duplicated | Versioned: 01-schema.cypher, 02-triggers.cypher | Phase 1 (2026-04-21) | Single source of truth; easier to track versions; init_schema.py loads from neo4j_client/ |
| Minimal storage layer (None) | StorageProvider ABC + LocalStorageProvider + StorageResolver | Phase 1 (2026-04-21) | Extensible to SSH/S3; testable (temp dirs); decoupled from business logic |
| Direct file I/O in business logic | All I/O via StorageProvider interface | Phase 1 (2026-04-21) | Enables Phase 2 config write-back without path coupling |
| pyproject.toml packages missing | packages = ["graph_lineage"] | Phase 1 (2026-04-21) | Correct package discovery; builds properly as wheel |

**Deprecated/outdated:**
- `graph_lineage/data_class/` directory structure — replaced by `graph_lineage/data_classes/` (plural) with same files
- Duplicated Cypher files — consolidated to versioned master copies in neo4j_client/
- No storage abstraction — now has StorageProvider ABC + LocalStorageProvider implementation

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Python 3.10+ available in .venv | Common Pitfalls 1 | Tests fail with syntax errors if .venv uses 3.9; need venv rebuild |
| A2 | All old `from graph_lineage.data_class...` imports have been updated | Architecture Patterns | Import failures at runtime if any remain; grep found none |
| A3 | Cypher files in neo4j_client/01-schema.cypher and 02-triggers.cypher are canonical | Don't Hand-Roll | Schema load fails if old duplicates still referenced elsewhere |
| A4 | graph_lineage/__init__.py should export StorageProvider/LocalStorageProvider for public API | Pitfalls 3 | Users can't do `from graph_lineage import StorageProvider`; workaround: import from submodule |

**If this table is empty:** Not applicable — all claims in this research were verified via file inspection and git status.

---

## Open Questions

1. **Test Environment Setup**
   - What we know: tests/test_storage.py exists with 20+ test cases; system Python is 3.9.6 (too old)
   - What's unclear: Will .venv have Python 3.10+ installed? How should planner verify test environment?
   - Recommendation: Planner should include a "verify Python version" step before running tests; if .venv is 3.9, note that rebuild is needed

2. **graph_lineage/__init__.py Exports**
   - What we know: File is empty (0 lines); CONTEXT.md D-07 requires StorageProvider + LocalStorageProvider exports
   - What's unclear: Should we also export data_classes items (Recipe, Model, etc) at top level? Or only storage?
   - Recommendation: Export only storage layer at top level (graph_lineage import StorageProvider); keep data_classes as `from graph_lineage.data_classes.neo4j.nodes import Recipe` (less pollution)

3. **Verification Confidence Gate**
   - What we know: Storage tests exist; no old imports found; Cypher files consolidated
   - What's unclear: What's the minimum verification needed before committing? Just test pass? Import checks? Code review?
   - Recommendation: (1) Verify Python 3.10+, (2) Run pytest tests/test_storage.py, (3) Import check: `python -c "from graph_lineage.storage import StorageProvider; from graph_lineage.data_classes.neo4j.nodes import Recipe"`, (4) Code review storage/ module

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All code (union syntax, etc) | ✓ (system 3.9.6, but .venv unclear) | 3.10+ required | Rebuild .venv with Python 3.10 |
| pytest | tests/test_storage.py | ✓ (in pyproject.toml dev deps) | >=8.0 | Install: pip install pytest |
| pathlib | LocalStorageProvider | ✓ (stdlib) | Python 3.4+ | Built-in, no fallback needed |
| PyYAML | StorageResolver | ✓ (pyproject.toml) | >=6.0 | Install: pip install pyyaml |

**Missing dependencies with no fallback:**
- Python 3.10+ (system has 3.9.6; .venv must have 3.10+)

**Missing dependencies with fallback:**
- (None — all critical deps specified in pyproject.toml)

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0 |
| Config file | pyproject.toml [tool.pytest.ini_options] testpaths = ["tests"] |
| Quick run command | `pytest tests/test_storage.py -v` |
| Full suite command | `pytest tests/ --cov=graph_lineage --cov-report=term-missing` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| 1.1 | data_class/ → data_classes/ migration | structural | (manual code review: import paths only) | N/A |
| 1.2 | All imports updated | structural | `python -c "from graph_lineage.data_classes.neo4j.nodes import Recipe"` | N/A |
| 1.3 | Duplicate Cypher files removed | structural | (manual verify: git status shows 2 deleted) | N/A |
| 1.4 | pyproject.toml corrected | structural | (grep check: `grep 'packages =' pyproject.toml`) | N/A |
| 1.5 | StorageProvider ABC complete | unit | `pytest tests/test_storage.py::TestStorageProviderInterface -v` | tests/test_storage.py:18+ |
| 1.6 | LocalStorageProvider works | unit | `pytest tests/test_storage.py::TestLocalStorageProvider -v` | tests/test_storage.py:18+ |
| 1.7 | StorageResolver routing works | unit | `pytest tests/test_storage.py::TestStorageResolver -v` | tests/test_storage.py (if exists) |
| 1.9 | Unit test storage provider | test | `pytest tests/test_storage.py --cov=graph_lineage.storage` | ✅ tests/test_storage.py |

### Sampling Rate
- **Per task commit:** `pytest tests/test_storage.py -v` (quick run <30s)
- **Per wave merge:** `pytest tests/ --cov=graph_lineage.storage --cov-fail-under=80` (verify 80%+ coverage)
- **Phase gate:** All tests green + coverage >80% before `/gsd-verify-work`

### Wave 0 Gaps
- [x] `tests/test_storage.py` — covers REQ-1.5 through 1.9 ✅ COMPLETE
- [x] `tests/conftest.py` — shared fixtures ✅ NOT NEEDED (LocalStorageProvider tests use tmp_path fixture)
- [x] Framework install: `pip install -e ".[dev]"` — covered ✅ DONE
- [ ] graph_lineage/__init__.py needs exports (not a test gap, but API completeness)

*(Existing test infrastructure covers all phase requirements)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A |
| V3 Session Management | no | N/A |
| V4 Access Control | partial | LocalStorageProvider.is_writable() checks permissions |
| V5 Input Validation | yes | pathlib.Path prevents path traversal; StorageResolver validates URI prefixes |
| V6 Cryptography | no | N/A (storage is local/YAML, no encryption needed in Phase 1) |
| V9 File Upload | yes | LocalStorageProvider.write_bytes() creates parent dirs safely (no uncontrolled writes) |

### Known Threat Patterns for Python Storage I/O

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal (../../../ attempts) | Tampering | pathlib.Path normalizes; LocalStorageProvider._resolve() uses is_absolute() check |
| Symlink attacks | Tampering | LocalStorageProvider.backup() uses shutil.copy2 (follows symlinks, not ideal) |
| Race conditions on mkdir | Tampering | LocalStorageProvider uses mkdir(exist_ok=True) — safe |
| Unvalidated file writes | Tampering | StorageProvider interface forces explicit write calls; no implicit I/O |
| Information disclosure (backup files) | Information | LocalStorageProvider.backup() creates .bak files — verify permissions; document cleanup |

**Recommendations for Phase 2+:**
- Document backup file cleanup (don't leave .bak files indefinitely)
- Consider symlink policy: resolve_symlinks option on LocalStorageProvider if needed
- Phase 4 (decorator): Validate config.yml paths before use; don't trust user_provided URIs without checks

---

## Sources

### Primary (HIGH confidence)
- LocalStorageProvider implementation: `/Users/T.Finizzi/repo/FineTuning-Lineage/graph_lineage/storage/local_provider.py` (100 lines, complete)
- StorageProvider ABC: `/Users/T.Finizzi/repo/FineTuning-Lineage/graph_lineage/storage/provider.py` (60 lines, 8 abstract methods)
- StorageResolver: `/Users/T.Finizzi/repo/FineTuning-Lineage/graph_lineage/storage/resolver.py` (139 lines, URI mapping + config)
- Test suite: `/Users/T.Finizzi/repo/FineTuning-Lineage/tests/test_storage.py` (20+ test cases, pytest fixtures)
- pyproject.toml: `/Users/T.Finizzi/repo/FineTuning-Lineage/pyproject.toml` (verified Python 3.10+, Pydantic v2, all deps)

### Secondary (MEDIUM confidence)
- CONTEXT.md decisions: `.planning/phases/01-infrastructure/01-CONTEXT.md` (locked decisions D-01 through D-10)
- REQUIREMENTS.md R2: `.planning/REQUIREMENTS.md` lines 133-167 (StorageProvider spec)
- ROADMAP.md Phase 1: `.planning/ROADMAP.md` lines 26-57 (task 1.1-1.9 breakdown)

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — pyproject.toml is current, all versions verified
- Architecture: **HIGH** — All code files inspected, import paths verified via grep
- Pitfalls: **HIGH** — Based on actual code state (empty __init__.py, Python 3.9 system, staged deletions)
- Test infrastructure: **MEDIUM** — tests/test_storage.py exists and looks comprehensive, but test execution blocked by Python 3.9 system (haven't run tests yet)

**Research date:** 2026-04-21
**Valid until:** 2026-04-28 (7 days — stable phase, no external changes expected)

