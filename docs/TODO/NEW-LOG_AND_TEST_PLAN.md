# NEW-LOG_AND_TEST_PLAN.md

## Executive Summary

This document unifies logging analysis and test scaffold findings, mapping discovered issues to their source tests, with recommended corrections and actions. It consolidates data from HTTP communication logs and test execution results across 5 run strategies.

---

## Part 1: HTTP Communication Issues

### Issue #1: Missing `base_experiment_id` in NEW Strategy Response

**Severity**: MEDIUM  
**Type**: Data Consistency / API Contract  
**Affected Tests**: ALL NEW strategy tests (8 tests)

#### Problem Description
When POST /api/v1/pre returns for NEW strategy, `base_experiment_id` is null instead of containing the experiment_id itself. This breaks lineage continuity for base experiments.

```json
// Current (WRONG):
{
  "experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793",
  "strategy": "NEW",
  "base": true,
  "base_experiment_id": null  // ❌ Should be "83ea4f48-0fc0-44ac-b39c-a5b36daa8793"
}

// Expected (CORRECT):
{
  "experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793",
  "strategy": "NEW",
  "base": true,
  "base_experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793"  // ✅ Self-reference for base
}
```

#### Root Cause
Server logic at `graph_lineage/setups/_base/modules/lineage/*.py` does not set `base_experiment_id` to self when creating base experiments (NEW strategy, base=true).

#### Log Files with This Issue
- http_test_test_new_detected_no_parent.log
- http_test_test_new_base_true.log
- http_test_test_new_no_edges_created.log
- http_test_test_new_stores_full_codebase.log
- http_test_test_multiple_new_experiments_separate.log
- http_test_test_http_logging_captures_pre_request.log
- http_test_test_log_file_format_validation.log
- http_communication.log

#### Affected Tests (from OLD_TEST_SCAFFOLD_SUMMARY.md)
- tests/integration_new_experiment.py - all 8 tests

#### Corrective Action Required
**File**: `graph_lineage/setups/_base/modules/lineage/pre_request_handler.py` (or equivalent)

Update NEW strategy handler to set:
```python
if strategy == "NEW" and base:
    base_experiment_id = experiment_id  # Self-reference
```

**Test Update**: Update assertions in integration_new_experiment.py to verify:
```python
assert response["base_experiment_id"] == response["experiment_id"]
```

---

### Issue #2: Missing `experiment_id` in Subsequent PRE Requests

**Severity**: HIGH  
**Type**: Request Payload Completeness  
**Affected Tests**: RETRY, BRANCH, RESUME, MERGE strategies with sequential requests

#### Problem Description
When sending a second (or subsequent) PRE request after a first run, the client should include the `experiment_id` from the prior response to establish parent-child relationships. However, this field is missing from request body.

```json
// Request Body (Missing experiment_id):
{
  // ❌ MISSING: "experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793"
  "experiment_name": "test-experiment",
  "experiment_uri": "...",
  "base_experiment_id": null,
  "previous_experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793",
  "description": null,
  "codebase": { ... }
}
```

#### Root Cause
LineageClient (or test code) does not pass prior experiment_id to subsequent calls. This breaks continuity in multi-step workflows.

#### Log Files with This Issue
- http_test_test_http_logging_multi_strategy_sequence.log (2nd request in sequence)

#### Affected Scenarios
- RETRY: retry same code → should link back to original
- BRANCH: modify code → should show as derived from parent
- RESUME: start from checkpoint → should show STARTED_FROM link
- MERGE: combine models → should track both predecessors

#### Corrective Action Required
**File**: `graph_lineage/setups/_base/modules/lineage/http_connector.py` (or client)

Update pre_execution() to pass experiment_id:
```python
def pre_execution(self, experiment_id: str = None) -> ExecutionContext:
    """Execute PRE request, optionally linking to parent experiment."""
    if experiment_id:
        self.experiment_id = experiment_id  # Store for use in request payload
    # ... build request with experiment_id included
```

**Test Update**: Update integration tests to chain requests:
```python
# First run (NEW)
ctx1 = lineage_client.pre_execution()

# Second run (RETRY)
ctx2 = lineage_client.pre_execution(experiment_id=ctx1.experiment_id)
assert ctx2.strategy == "RETRY"
```

---

### Issue #3: Inconsistent `description` Field Handling

**Severity**: MEDIUM  
**Type**: Data Loss / Metadata Handling  
**Affected Tests**: RETRY strategy (multi-step sequences)

#### Problem Description
In multi-step sequences, the first response includes `description` ("Initial experiment (base)"), but when sending the second request, the description field becomes null and is not preserved/propagated.

```json
// First Response:
{
  "experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793",
  "description": "Initial experiment (base)"  // ✅ Present
}

// Second Request Body:
{
  "previous_experiment_id": "83ea4f48-0fc0-44ac-b39c-a5b36daa8793",
  "description": null  // ❌ Lost
}
```

#### Root Cause
Client code does not retrieve and forward description from previous experiment when setting up next run. Comment in log notes: "maybe deleted before sending to server, to investigate in setups/_base/modules/lineage/*.py"

#### Log Files with This Issue
- http_test_test_http_logging_multi_strategy_sequence.log (line with comment about missing description)

#### Corrective Action Required
**File**: `graph_lineage/setups/_base/modules/lineage/pre_request_builder.py` (or equivalent)

Add logic to preserve experiment metadata:
```python
def build_retry_request(prior_response, config):
    """Build next request preserving metadata from prior run."""
    return {
        "previous_experiment_id": prior_response["experiment_id"],
        "description": prior_response.get("description", ""),  # Preserve
        # ... rest of payload
    }
```

**Test Update**: Verify description is maintained in RETRY chain:
```python
assert ctx2.description == ctx1.description  # Same description
```

---

### Issue #4: Empty `changed_files` in NEW Strategy

**Severity**: LOW  
**Type**: Clarification / Documentation  
**Affected Tests**: All NEW strategy tests

#### Problem Description
NEW strategy returns `changed_files: []` which is correct (new experiment, no prior to compare), but comment suggests system should optionally store entire codebase as baseline snapshot.

```json
{
  "strategy": "NEW",
  "changed_files": []  // Correct, but confirm codebase storage behavior
}
```

Comment in logs: "NO changes, but system can store entire codebase if NEW is the strategy (check server behavior)"

#### Root Cause
Unclear whether entire codebase is stored during NEW strategy execution. Test assertions don't verify codebase storage behavior.

#### Log Files with This Issue
- All NEW strategy logs show this pattern
- http_communication.log, http_test_test_*.log (all)

#### Corrective Action Required (Documentation)
**File**: `docs/LOGGING_BEHAVIOR.md` (new)

Document:
```markdown
## NEW Strategy Codebase Handling

- changed_files: empty array (no prior to compare)
- Codebase Storage: entire snapshot stored in experiment node
- Rationale: Baseline needed for future BRANCH/RETRY comparisons
```

**Test Update**: Add assertion to verify codebase is stored:
```python
def test_new_stores_full_codebase(lineage_client, mock_neo4j):
    ctx = lineage_client.pre_execution()
    exp = mock_neo4j.get_experiment(ctx.experiment_id)
    assert exp.codebase is not None
    assert len(exp.codebase) > 0  # Verify files stored
```

---

### Issue #5: Missing `metrics_uri` in POST Requests

**Severity**: LOW  
**Type**: Optional Field Logging  
**Affected Tests**: POST /api/v1/post tests

#### Problem Description
POST request doesn't include `metrics_uri` field. Comment notes: "MISSED, but to verify in setups/_base/modules/lineage/*.py"

#### Log Files with This Issue
- http_test_test_new_post_updates_status.log
- http_test_test_new_post_with_failed_status.log

#### Root Cause
POST endpoint may not require metrics_uri as request field, or it's computed server-side from config.yml output.metrics_uri.

#### Corrective Action Required
**Verification Only**: Confirm whether metrics_uri should be:
1. Passed in POST request, OR
2. Computed from config.yml, OR  
3. Not needed for POST flow

**Test Update**: Add comment to clarify:
```python
# POST doesn't include metrics_uri - should be from config.yml:
#   output:
#     metrics_uri: /logs/${experiment.id}/metrics.json
```

---

## Part 2: Evaluation Loss Logging Issues

### Issue #6: Missing `eval_loss` Entries in Log History

**Severity**: MEDIUM  
**Type**: Metrics Logging / Trainer Configuration  
**Affected Components**: All plot functions (loss.py, eval_loss.py)

#### Problem Description
During training, `eval_loss` is not logged at every step. The log_history may have many train loss entries but few (or zero) eval loss entries. This causes plots to:
- Show warning: "⚠ NO EVAL LOSS FOUND"
- Render empty eval_loss.png
- Fail to detect overfitting patterns

#### Root Cause
Missing or misconfigured trainer settings:
1. **eval_steps not set** in config.yml training section
2. **eval_size = 0** (no evaluation set)
3. **eval_strategy = "no"** (evaluation disabled)
4. Trainer callback not logging eval metrics to log_history

#### Code Evidence
**File**: `graph_lineage/setups/_base/modules/plots/plot_func/loss.py` (lines 55-56)
```python
if not evals:
    logger.warning("plot_loss: no eval-loss entries found in log_history; ensure eval_size > 0 and eval_steps configured")
    # Line 93-96: Shows warning box on plot
    ax.text(0.98, 0.05, "⚠ NO EVAL LOSS FOUND", ...)
```

**File**: `graph_lineage/setups/_base/modules/plots/plot_func/eval_loss.py` (lines 50-51)
```python
if not evals:
    logger.warning("plot_eval_loss: no eval_loss entries found in log_history.")
    # Lines 52-57: Creates empty plot
```

#### Affected Plots
- output_dir/loss.png - Train loss shows, eval loss missing
- output_dir/eval_loss.png - Completely empty

#### Affected Tests
Any test that:
1. Runs training without eval_steps
2. Doesn't set eval_size > 0
3. Uses trainer without eval callback

#### Corrective Action Required

**Action 1: Update config.yml Templates**
File: `graph_lineage/setups/*/config.yml`

Add to all training configs:
```yaml
training:
  eval_steps: 50          # Evaluate every N steps
  eval_strategy: "steps"  # vs "no" (disabled) or "epoch"
  eval_size: 0.1          # Reserve 10% of train data for eval
  per_device_eval_batch_size: 8
```

**Action 2: Update Trainer Initialization**
File: `graph_lineage/setups/_base/modules/callbacks/metrics_saver.py`

Ensure trainer logs eval metrics:
```python
def setup_trainer(model, config):
    training_args = TrainingArguments(
        eval_steps=config.training.get("eval_steps", 50),
        eval_strategy=config.training.get("eval_strategy", "steps"),
        logging_steps=1,  # Log every step (for train loss)
        save_steps=100,
    )
    trainer = DPOTrainer(
        model,
        args=training_args,
        callbacks=[MetricsSaver(log_history)],  # Ensure callback captures eval
    )
    return trainer
```

**Action 3: Add Integration Test for eval_loss**
File: `tests/test_eval_loss_logging.py` (NEW)

```python
def test_eval_loss_logged_with_eval_steps(lineage_client, mock_trainer):
    """Verify eval_loss is logged when eval_steps is configured."""
    config = ConfigBuilder().with_eval_steps(50).with_eval_size(0.1).build()
    
    # Run trainer
    log_history = mock_trainer.train(config)
    
    # Verify eval_loss entries exist
    evals = [e for e in log_history if "eval_loss" in e]
    assert len(evals) > 0, "No eval_loss entries found"
    
    # Plot should not show warning
    output_dir = Path("output")
    plot_path = plot_loss(log_history, output_dir)
    assert plot_path.exists()
    
    # Check plot doesn't have warning text
    with open("test_log.txt") as f:
        logs = f.read()
        assert "NO EVAL LOSS FOUND" not in logs
```

**Action 4: Documentation Update**
File: `docs/PLOTTING_AND_METRICS.md` (NEW)

```markdown
## Evaluation Loss Logging

### Prerequisites for eval_loss Plots
1. `eval_steps` configured (e.g., 50)
2. `eval_strategy` = "steps" or "epoch" (not "no")
3. `eval_size` > 0 (e.g., 0.1 for 10% of data)
4. At least one evaluation during training

### Troubleshooting "NO EVAL LOSS FOUND"
- Check config.yml has eval_steps set
- Verify dataset size > eval_steps (e.g., dataset=1000, eval_steps=50)
- Check trainer callbacks include MetricsSaver
- Run: grep -r "eval_loss" logs/ to confirm logging

### Plot Output
- loss.png: shows both train loss and eval loss (if available)
- eval_loss.png: focused eval loss with smoothing and statistics
```

---

## Part 3: Test Scaffold Status Summary

### Test Coverage Matrix

| Strategy | Test File | Count | Status | Issues |
|----------|-----------|-------|--------|--------|
| NEW | integration_new_experiment.py | 8 | ✅ Passing | #1: base_experiment_id |
| RETRY | integration_retry_experiment.py | 5 | ✅ Passing | #2: missing experiment_id |
| BRANCH | integration_branch_experiment.py | 5 | ✅ Passing | #2: missing experiment_id |
| RESUME | integration_resume_experiment.py | 4 | ✅ Passing | #2: missing experiment_id |
| MERGE | integration_merge_experiment.py | 3 | ⚠️ Failing | Design mismatch |
| Checkpoints | integration_checkpoint_callbacks.py | 6 | ✅ Passing | None critical |
| Error Cases | integration_error_cases.py | 6 | ⚠️ Partial | Server behavior discrepancies |
| HTTP Logging | test_http_logging_demo.py | 3 | ✅ Passing | None |

### Overall Test Results
- **Total Tests**: 41
- **Passing**: 35 (85%)
- **Failing**: 6 (15%)
- **HTTP Logs Generated**: 10 files, ~32 KB

---

## Part 4: Implementation Roadmap

### Phase 1: Critical Fixes (Blocking)
**Effort**: 2-3 hours  
**Priority**: HIGH

1. **Fix Issue #1** - base_experiment_id self-reference
   - Files: pre_request_handler.py
   - Tests: integration_new_experiment.py (update assertions)
   - Verification: All 8 NEW tests pass with correct base_experiment_id

2. **Fix Issue #2** - experiment_id in subsequent requests
   - Files: http_connector.py, pre_request_builder.py
   - Tests: All multi-strategy tests (update to chain requests)
   - Verification: RETRY, BRANCH, RESUME chains work correctly

3. **Fix Issue #6** - eval_loss logging
   - Files: config.yml (all setups), metrics_saver.py
   - Tests: test_eval_loss_logging.py (new)
   - Verification: All plots show eval_loss without warnings

### Phase 2: Data Quality (Important)
**Effort**: 1-2 hours  
**Priority**: MEDIUM

4. **Fix Issue #3** - description preservation
   - Files: pre_request_builder.py
   - Tests: integration_retry_experiment.py (add assertion)
   - Verification: Description maintained across retries

5. **Fix Issue #4** - codebase storage documentation
   - Files: LOGGING_BEHAVIOR.md (new)
   - Tests: integration_new_experiment.py (add codebase assertions)
   - Verification: Tests document and verify storage behavior

### Phase 3: Polish (Optional)
**Effort**: 30 minutes  
**Priority**: LOW

6. **Fix Issue #5** - metrics_uri clarification
   - Files: PLOTTING_AND_METRICS.md (new)
   - Tests: Comment update only
   - Verification: Clear documentation of metrics flow

---

## Part 5: Test Execution Checklist

Before marking issues resolved:

- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Verify all 41 tests pass
- [ ] Check HTTP logs are clean (no MISSING comments)
- [ ] Run plots on sample training run
- [ ] Verify loss.png shows eval_loss curve
- [ ] Verify eval_loss.png renders correctly
- [ ] Check no "NO EVAL LOSS FOUND" warnings appear
- [ ] Update MEMORY.md with completion status

---

## Part 6: References

### Log Files Analyzed
- http_communication.log
- http_test_test_http_logging_captures_pre_request.log
- http_test_test_http_logging_multi_strategy_sequence.log
- http_test_test_log_file_format_validation.log
- http_test_test_multiple_new_experiments_separate.log
- http_test_test_new_base_true.log
- http_test_test_new_detected_no_parent.log
- http_test_test_new_no_edges_created.log
- http_test_test_new_post_updates_status.log
- http_test_test_new_post_with_failed_status.log
- http_test_test_new_stores_full_codebase.log

### Source Documents
- OLD_TEST_SCAFFOLD_SUMMARY.md (test infrastructure baseline)
- OLD_HTTP_LOGGING_SUMMARY.md (logging implementation)

### Code Files Implicated
- graph_lineage/setups/_base/modules/lineage/pre_request_handler.py
- graph_lineage/setups/_base/modules/lineage/http_connector.py
- graph_lineage/setups/_base/modules/lineage/pre_request_builder.py
- graph_lineage/setups/_base/modules/plots/plot_func/loss.py
- graph_lineage/setups/_base/modules/plots/plot_func/eval_loss.py
- graph_lineage/setups/_base/modules/callbacks/metrics_saver.py
- All config.yml files in setups/*/

---

## Conclusion

This document provides a unified view of 6 distinct issues discovered through HTTP logging analysis and test execution:
1. Data consistency issues (base_experiment_id, experiment_id, description)
2. Metrics logging gaps (eval_loss)

Each issue is mapped to affected tests, log evidence, and corrective actions. Implementation prioritizes fixing critical lineage tracking issues (#1, #2) and metrics logging (#6) before addressing documentation and clarifications (#3-5).

**Next Step**: Begin Phase 1 fixes with Issue #1 (base_experiment_id) in pre_request_handler.py.
