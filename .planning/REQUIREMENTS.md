# REQUIREMENTS.md — Core Lineage Tracking System v1.0

## Epic: Hook-Based Experiment Tracking with DiffManager

**Goal**: Users can decorate a training function with `@envelope.tracker()`, and the system automatically:
1. Reads config.yml
2. Validates it against schema
3. Detects if this is NEW/RETRY/BRANCH/RESUME/MERGE via DiffManager
4. Creates Neo4j nodes for Experiment + Recipe + Model + Component (if new)
5. Handles pre/post-execution lifecycle (metrics, checkpoints, state)
6. Writes back config.yml with generated UUIDs

---

## Requirements by Category

### R1: Configuration Schema & Validation (PHASE 2)

#### R1.1 Config YAML Structure
```yaml
experiment:
  id: <uuid or null>           # Generated on NEW, preserved on BRANCH/RETRY
  derived_from: <uuid or null> # Parent experiment (set on BRANCH/RETRY)
  base_experiment: <uuid>      # Root experiment (set on NEW, preserved after)
  expected_run_type: "auto"    # "auto" or conflict_policy controls

model:
  - model_name: "llama-7b"  # Must exist in DB (created via UI)
    hyperparameters:
      learning_rate: 0.001
      batch_size: 32
      # ... framework-specific params

recipe:
  id: <uuid>  # Must exist in DB (created via UI)
  name: "my_recipe"
  scope: "sft"
  tasks: ["task1", "task2"]
  derived_from: <uuid or null>
  entries:
    /path/to/dataset/ARC:
      chat_type: "context_chat"
      dist_id: "uuid"
      dist_name: "mapped__ARC"
      dist_uri: "/path/to/dataset/ARC"
      replica: 1
      samples: 2590
      tokens: 179178
      words: 129464
      system_prompt: []
      system_prompt_name: []
      validation_error: null

output:
  output_dir: /nfs/training-output/.dpo-cache/checkpoints
  metrics_uri: /nfs/training-output/.dpo-cache/metrics

component:
  - framework: "unsloth"      # Identifies implementation (PyTorch, etc)
  - technique: "dpo"          # Algorithm (DPO, GRPO, etc)

hardware:  # Optional, SkyPilot integration
  resources:
    infra: "aws"
    accelerators: "A100:8"
  setup: |
    echo "Setup commands"
  run: |
    echo "Run commands"

model_merging:  # Optional, mutually exclusive strategies
  - merge_ckp:     # List of checkpoint URIs
    - "uri_ckp_1"
    - "uri_ckp_2"
  # OR (not AND)
  - merge_models:  # List of model names/URIs
    - "llama-7b"
    - "mistral-7b"
  # OR (not AND)
  - merge_model_ckp:  # Model + adapter
    - model: "llama-7b"
    - adapter: "adapter_uri"
```

**Acceptance Criteria:**
- [ ] Pydantic model parses all fields with correct types
- [ ] YAML → Python → YAML round-trip preserves all data
- [ ] Missing required fields caught PRE-EXECUTION → exit(2)
- [ ] UUID validation (format check)
- [ ] List fields default to empty if missing
- [ ] Component fields are optional (can be inferred from config)

---

#### R1.2 Config Validation (PRE-EXECUTION)

**Blockers (exit 2):**
- [ ] YAML malformed (parse error)
- [ ] experiment.base_experiment is malformed UUID (not null)
- [ ] model.model_name missing → BlockMessage: "model.model_name required"
- [ ] recipe.id missing → BlockMessage: "recipe.id required"
- [ ] output.metrics_uri missing/unreachable
- [ ] output.output_dir missing/unreachable
- [ ] Model name not in DB → BlockMessage: "Model {name} not found in DB. Create via UI first."
- [ ] Recipe ID not in DB → BlockMessage: "Recipe {id} not found in DB. Create via UI first."
- [ ] expected_run_type conflict (user says "retry" but files changed) → BlockMessage: "Conflict: expected_run_type='retry' but file_changes={files}. Set expected_run_type='auto' or fix files."
- [ ] model_merging has multiple strategies selected → BlockMessage: "model_merging: only ONE of [merge_ckp, merge_models, merge_model_ckp] allowed"
- [ ] model_merging strategy is empty list → BlockMessage: "model_merging.{strategy}: empty list"

**Warnings (logged, execution continues):**
- component fields not provided (infer from model_name)

---

#### R1.3 Config Write-Back (POST-NEW/BRANCH/RETRY)

After decorator creates Experiment node:
- [ ] Write `experiment.id = <generated-uuid>`
- [ ] Write `experiment.derived_from = <parent-uuid>` (if BRANCH/RETRY, else null)
- [ ] Atomic file write (backup original, write new, verify)
- [ ] Preserve YAML formatting (comments, indentation)

**Acceptance Criteria:**
- [ ] config.yml updated immediately after node creation
- [ ] UUID persists across restarts
- [ ] File write is atomic (no partial writes on crash)
- [ ] Original file backed up (optional but nice to have)

---

### R2: Storage Abstraction (PHASE 1)

#### R2.1 StorageProvider Interface

```python
class StorageProvider(ABC):
    async def exists(self, path: str) -> bool:
        """Check if path exists"""

    async def read(self, path: str) -> bytes:
        """Read file contents"""

    async def write(self, path: str, data: bytes) -> None:
        """Write file contents"""

    async def walk(self, path: str) -> Iterable[str]:
        """Recursive file listing (for codebase snapshot)"""
```

#### R2.2 Implementations
- [ ] LocalStorageProvider (filesystem via pathlib)
- [ ] [Future] SSHStorageProvider (SFTP)
- [ ] [Future] S3StorageProvider

#### R2.3 Universal Path Resolver
- [ ] Parse URI prefix (e.g., `s3://bucket/path` → S3StorageProvider)
- [ ] Config file `.storage-config.yml` maps prefixes to providers
- [ ] PRE-EXECUTION: validate all URIs are accessible

**Acceptance Criteria:**
- [ ] All output URIs are checked for existence
- [ ] Clear error if unreachable (exit 2 or 3)
- [ ] Extension point for custom providers

---

### R3: DiffManager & Branching Logic (PHASE 3)

#### R3.1 CodeSnapshot
- [ ] Serialize all critical files to JSON:
  ```json
  {
    "train.py": "def train()...",
    "prepare.py": "def prepare()...",
    "requirements.txt": "torch==2.0\n...",
    "config.yml": "experiment:\n..."
  }
  ```
- [ ] Exclude files starting with `.`
- [ ] Store snapshot on filesystem (via StorageProvider)
- [ ] Load previous snapshot for comparison

**Acceptance Criteria:**
- [ ] Snapshot captures exactly 4 critical files
- [ ] Binary files skipped gracefully
- [ ] Round-trip serialization works (JSON → files)

---

#### R3.2 DiffAnalyzer (diff_match_patch integration)
- [ ] Compare prev_snapshot vs current_snapshot
- [ ] Output: `{filename: {"diffs": [...], "patch": "..."}}`
- [ ] Identify critical_file_changes (which files changed)
- [ ] Generate commit message (if critical files changed):
  - `[auto] {filename} changed` for each critical file
  - Only for: train.py, prepare.py, config.yml, requirements.txt
  - Comma-separated if multiple

**Acceptance Criteria:**
- [ ] Diff JSON is valid + can be stored in Neo4j
- [ ] Commit message auto-generated correctly
- [ ] Non-critical file changes don't trigger message

---

#### R3.3 RuleEngine (Branching Decisions)

**Decision tree:**
```
IF base_experiment == null AND derived_from == null:
    → NEW (create first Experiment)
ELIF model_merging is present:
    → MERGE (validate strategy, override all else)
ELIF critical_files_changed:
    → BRANCH (+ DERIVED_FROM edge + diff_patch)
ELIF checkpoint_resume_from is specified:
    → RESUME (+ STARTED_FROM edge)
ELSE:
    → RETRY (+ RETRY_OF edge)
```

**Conflict handling:**
- If expected_run_type == "retry" but critical_files_changed:
  - Exit(5) + BlockMessage: "Conflict: ..."

**Acceptance Criteria:**
- [ ] All 4 paths (NEW, RETRY, BRANCH, RESUME) correctly identified
- [ ] MERGE overrides all other logic
- [ ] Conflict detection works
- [ ] RuleEngine outputs (run_type, diff_patch, commit_msg)

---

### R4: Hook/Decorator System (PHASE 4)

#### R4.1 @envelope.tracker() Decorator

**Usage:**
```python
from envelope.lineage import envelope

@envelope.tracker()
def train_loop(config_path: str, device: str):
    # User code
    pass

# Or with explicit config:
@envelope.tracker(config_path="/path/to/config.yml")
def train_loop(device: str):
    pass
```

#### R4.2 PRE-EXECUTION Phase

**Steps:**
1. Load config.yml from root (or explicit path)
2. Validate (exit 2 on error)
3. Read previous experiment snapshot (if exists)
4. DiffManager.decide() → run_type
5. Neo4j:
   - Create Experiment node (id, status=RUNNING, run_type, created_at)
   - Ensure Recipe node exists (create if missing)
   - Ensure Model node exists (create if missing)
   - Ensure Component node exists (create if missing)
   - Link relationships (USES_RECIPE, USES_MODEL, USES_COMPONENT)
   - If BRANCH/RETRY: DERIVED_FROM or RETRY_OF edge
6. Write config.yml (update experiment.id + derived_from)
7. Log: "Experiment {id} started as {run_type}"
8. Return to user function

**Acceptance Criteria:**
- [ ] Config validated (all exit 2 cases blocked)
- [ ] Experiment node created with correct run_type
- [ ] All relationships created
- [ ] config.yml updated atomically
- [ ] Logging clear + actionable
- [ ] No crash if Neo4j unavailable (warn, continue? or block?)

---

#### R4.3 POST-EXECUTION Phase (on exit 0)

**Steps:**
1. Read training_metrics_URI + hw_metrics_URI files
2. Scan output_dir for checkpoint files
3. For each checkpoint found:
   - Extract metrics (if present in hw_metrics_URI)
   - Name: `{model_name}_ckp_{serial}_{exp_uuid_short}`
   - Create Checkpoint node in Neo4j
   - Link to Experiment (PRODUCED edge)
4. If model_merging in config:
   - Parse merge strategy
   - Create merged Checkpoint node
   - Link sources (MERGED_FROM edges N→1)
5. Update Experiment.status = "COMPLETED"
6. Save snapshot_T to storage (for next run)
7. Return normally (exit 0)

**Acceptance Criteria:**
- [ ] Checkpoints named correctly
- [ ] Checkpoint nodes created with metrics
- [ ] PRODUCED edges created
- [ ] Merge logic works (all 3 strategies)
- [ ] Experiment status updated
- [ ] Exit code 0 on success

---

#### R4.4 Failure Handler (on exit 1)

**Steps:**
1. Catch exception/exit code from user function
2. Update Experiment.status = "FAILED"
3. Log exit code 1 + message + stacktrace
4. Save any partial metrics (if written to URIs)
5. Exit process with code 1

**Acceptance Criteria:**
- [ ] Status updated before exit
- [ ] Error logged with full context
- [ ] Process exits with code 1

---

#### R4.5 Error Handling (Validation Errors)

| Error Case | Exit Code | Action | Log Level |
|-----------|-----------|--------|-----------|
| Config YAML parse error | 2 | Block train | ERROR |
| Missing required field | 2 | Block train | ERROR |
| Storage URI unreachable | 2/3 | Block train | ERROR |
| Model not in DB | 2 | Block train | ERROR |
| Recipe not in DB | 2 | Block train | ERROR |
| run_type conflict | 5 | Block train | ERROR |
| model_merging invalid | 2 | Block train | ERROR |
| Training crashed | 1 | Capture exit | ERROR |
| Neo4j unavailable | 4 | Block train | ERROR |

**Acceptance Criteria:**
- [ ] All exit codes match specification
- [ ] BlockMessages are clear + actionable
- [ ] Stacktraces logged on crash
- [ ] Experiment node created or marked FAILED

---

### R5: Neo4j Integration (PHASE 4)

#### R5.1 Experiment Node Creation

```cypher
CREATE (e:Experiment {
  id: "uuid",
  run_type: "BRANCH",
  status: "RUNNING|COMPLETED|FAILED",
  created_at: datetime(),
  updated_at: datetime(),
  config_hash: "sha256",
  code_hash: "sha256",
  metrics_uri: "/path/to/metrics",
  hw_metrics_uri: "/path/to/hw"
})
```

#### R5.2 Relationships

- USES_RECIPE: Experiment → Recipe
- USES_MODEL: Experiment → Model
- USES_COMPONENT: Experiment → Component
- DERIVED_FROM {diff_patch: JSON, commit_msg: str}: NEW_Exp → PREV_Exp
- RETRY_OF: NEW_Exp → PREV_Exp
- STARTED_FROM: NEW_Exp → Checkpoint (if resume_from)
- PRODUCED_BY: Checkpoint → Experiment
- MERGED_FROM: Checkpoint_merged → [Checkpoint1, Checkpoint2, ...]

#### R5.3 Checkpoint Node Creation

```cypher
CREATE (c:Checkpoint {
  id: "uuid",
  name: "llama7b_ckp_0_e2f54a3a",
  series: 0,
  epoch: 5,
  metrics: {loss: 0.23, perplexity: 10.5},
  uri: "/mnt/checkpoints/ckp_5",
  created_at: datetime()
})
```

**Acceptance Criteria:**
- [ ] All nodes created with correct properties
- [ ] All relationships created with correct direction
- [ ] Timestamps auto-set
- [ ] Metrics properly JSON-serialized
- [ ] No orphan checkpoints (all have PRODUCED_BY or MERGED_FROM)

---

### R6: Integration & Testing (PHASE 5)

#### R6.1 Scenarios

**Scenario 1: NEW** (first run, no prior experiment)
- config.yml: base_experiment=null, derived_from=null
- Expected: Experiment created as NEW
- Assert: experiment.id generated + written to config.yml

**Scenario 2: RETRY** (same config, same code)
- config.yml: base_experiment=<uuid>, experiment.id=<prev_uuid>
- Files unchanged (same hash)
- Expected: New Experiment created with RETRY_OF edge
- Assert: run_type="RETRY", RETRY_OF edge created

**Scenario 3: BRANCH** (config or code changed)
- config.yml: base_experiment=<uuid>, experiment.id=<prev_uuid>
- Change: train.py modified (critical file)
- Expected: New Experiment created with DERIVED_FROM edge
- Assert: run_type="BRANCH", diff_patch on edge, commit_msg auto-generated

**Scenario 4: RESUME** (same config but specific checkpoint)
- config.yml: checkpoint_resume_from=<uuid>
- Files unchanged
- Expected: New Experiment with STARTED_FROM edge
- Assert: run_type="RESUME", can resume from checkpoint

**Scenario 5: MERGE** (model_merging specified)
- config.yml: model_merging.merge_ckp = [<uuid1>, <uuid2>]
- Expected: New Checkpoint created via merge.py
- Assert: MERGED_FROM edges created correctly

#### R6.2 Test Coverage
- [ ] Unit tests: >80% coverage on logic modules (DiffManager, RuleEngine, validation)
- [ ] Integration tests: All 5 scenarios end-to-end
- [ ] Error cases: All exit codes verified
- [ ] Neo4j queries: Verify nodes + relationships created

**Acceptance Criteria:**
- [ ] All 5 scenarios pass
- [ ] Exit codes correct for all cases
- [ ] Neo4j shows correct nodes + relationships
- [ ] Coverage >80%

---

### R7: Documentation (PHASE 6)

#### R7.1 docs/MIDDLEWARE.md
- Architecture diagram (Decorator → DiffManager → DiffAnalyzer → RuleEngine → Neo4j)
- For each run type: config example + expected Neo4j state
- Troubleshooting section

#### R7.2 docs/CONFIG.md
- Full config.yml reference (all fields annotated)
- Component options (frameworks, techniques)
- model_merging strategies explained
- Storage URI format

#### R7.3 docs/EXAMPLES.md
- Example 1: Single-node training (NEW)
- Example 2: Hyperparameter sweep (BRANCH)
- Example 3: Resume from checkpoint (RESUME)
- Example 4: Model merging (MERGE)

#### R7.4 docs/ERROR_HANDLING.md (User-facing)
- Exit code table
- Common errors + fixes
- Stacktrace interpretation

#### R7.5 README.md Updates
- Architecture diagram
- Quick start ("pip install, sample config, run")
- Links to docs/

**Acceptance Criteria:**
- [ ] All docs clear + with code examples
- [ ] New users can follow examples
- [ ] Error messages link to docs

---

### R8: Verification & Polish (PHASE 7-8)

#### R8.1 Code Quality
- [ ] No linter warnings (ruff)
- [ ] Type hints on public functions
- [ ] Docstrings on classes + public methods
- [ ] No security issues (no hardcoded secrets, no shell injection, etc)

#### R8.2 Test Execution
- [ ] pytest --cov envelope/ tests/ → >80% coverage
- [ ] No failing tests
- [ ] All scenarios passing

#### R8.3 Manual E2E Test
- [ ] docker-compose up (Neo4j starts)
- [ ] Run all 5 scenarios locally
- [ ] Streamlit UI shows correct nodes + relationships
- [ ] Exit codes all correct

**Acceptance Criteria:**
- [ ] No warnings
- [ ] All tests pass
- [ ] Coverage >80%
- [ ] Full E2E works locally

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Exit code correctness | 100% (all cases verified) |
| Unit test coverage | >80% |
| Integration test pass rate | 100% (all 5 scenarios) |
| Decorator overhead | <100ms |
| Config write-back atomicity | 100% (no data loss) |
| Documentation completeness | All pages written + reviewed |
| Code review issues | 0 high-severity |

---

## Out of Scope (v1.1+)

- [ ] Async refactoring
- [ ] Remote worker communication (SSH, HTTP)
- [ ] Advanced UI (visualization, lineage browser)
- [ ] S3/GCS storage providers
- [ ] Distributed training support
- [ ] GPU resource management

---

## Sign-Off

- **Product Owner**: User (you)
- **Technical Lead**: Claude (planning + implementation)
- **Status**: Ready for phase planning (PHASE 1 kickoff)
