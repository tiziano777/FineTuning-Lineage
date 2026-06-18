# HTTP Communication Logging Implementation Summary

## Overview
Implemented comprehensive HTTP communication logging for test suite. Each HTTP test creates its own log file capturing all requests/responses with full request/response bodies.

## What's New

### 1. **Per-Test HTTP Logging**
- Each test that uses `lineage_client` automatically creates: `tests/http_test_<test_name>.log`
- No file overwrites - every test has dedicated log file
- Concurrent test runs won't interfere with each other

### 2. **Log File Format**
```
2026-06-17 16:22:11 [INFO] http_connector_test_test_new_detected_no_parent - → POST /api/v1/pre
2026-06-17 16:22:11 [DEBUG] http_connector_test_test_new_detected_no_parent -   Body: {
  "experiment_name": "test-experiment",
  "experiment_uri": "...",
  "codebase": { ... full JSON body ... }
}
2026-06-17 16:22:11 [INFO] http_connector_test_test_new_detected_no_parent - ← 200 POST /api/v1/pre
2026-06-17 16:22:11 [DEBUG] http_connector_test_test_new_detected_no_parent -   Response: {
  "experiment_id": "...",
  "strategy": "NEW",
  ...
}
```

### 3. **Log Levels**
- **INFO**: Request/response markers with arrows (`→`/`←`) and status codes
  - Example: `→ POST /api/v1/pre` and `← 200 POST /api/v1/pre`
- **DEBUG**: Full JSON request/response bodies (formatted, indented)

## Created Log Files (Test Run)
10 HTTP test log files created in last run:

1. `http_test_test_http_logging_captures_pre_request.log` - 2.9K
2. `http_test_test_http_logging_multi_strategy_sequence.log` - 6.1K (2 HTTP calls)
3. `http_test_test_log_file_format_validation.log` - 2.9K
4. `http_test_test_multiple_new_experiments_separate.log` - 2.9K
5. `http_test_test_new_base_true.log` - 2.8K
6. `http_test_test_new_detected_no_parent.log` - 2.9K
7. `http_test_test_new_no_edges_created.log` - 2.9K
8. `http_test_test_new_post_updates_status.log` - 3.5K
9. `http_test_test_new_post_with_failed_status.log` - 3.6K
10. `http_test_test_new_stores_full_codebase.log` - 2.9K

**Total**: ~32 KB of detailed HTTP communication logs

## Implementation Details

### Modified Files

#### 1. `tests/mock_http_connector.py`
**Changes**:
- Added imports: `json`, `logging`
- `FastAPITestTransport.__init__()`: now accepts optional `logger` parameter
- `handle_request()`: logs all HTTP traffic
  - Request: `→ METHOD /path` (INFO) + request body (DEBUG)
  - Response: `← STATUS METHOD /path` (INFO) + response body (DEBUG)
- `TestHttpConnector.__init__()`: passes logger to transport

**Code patterns**:
```python
self._logger.info(f"→ {request.method} {request.url.path}")
if request.content:
    try:
        body = json.loads(request.content)
        self._logger.debug(f"  Body: {json.dumps(body, indent=2)}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        self._logger.debug(f"  Body: {request.content[:100]}")
```

#### 2. `tests/conftest.py`
**Changes**:
- Added import: `logging`
- New fixture `http_logger(request)`:
  - Creates logger unique to each test: `http_connector_test_{test_name}`
  - Creates per-test log file: `tests/http_test_{test_name}.log`
  - File handler (DEBUG) logs all details
  - Console handler (INFO) shows summary on stdout
  - Cleanup: closes handlers after test
- Updated `lineage_client` fixture to accept and pass `http_logger` to `TestHttpConnector`

**Key logic**:
```python
test_name = request.node.name.replace("/", "_").replace("::", "_")
log_file = Path(__file__).parent / f"http_test_{test_name}.log"
logger = logging.getLogger(f"http_connector_test_{test_name}")
```

#### 3. `tests/test_http_logging_demo.py` (NEW)
**Purpose**: Demonstrate HTTP logging functionality
**Tests**:
1. `test_http_logging_captures_pre_request` - verifies request/response capture and JSON formatting
2. `test_http_logging_multi_strategy_sequence` - verifies multiple sequential requests logged
3. `test_log_file_format_validation` - verifies log format (timestamp, levels, arrows)

**Status**: 3/3 passing ✅

## How to Use

### View HTTP logs for a specific test
```bash
# After running tests, view log for a specific test
cat tests/http_test_test_new_detected_no_parent.log

# Or use grep to search
grep "experiment_id" tests/http_test_test_new_detected_no_parent.log

# View just request arrows
grep "→\|←" tests/http_test_test_new_detected_no_parent.log

# View debug details (request/response bodies)
grep -A 20 "→ POST" tests/http_test_test_new_detected_no_parent.log
```

### Enable logging in new tests
```python
def test_my_http_feature(lineage_client, mock_neo4j, http_logger):
    # http_logger is automatically created with per-test log file
    ctx = lineage_client.pre_execution()
    # All HTTP traffic logged to tests/http_test_test_my_http_feature.log
```

### Check logging during development
```bash
# Run a specific test with logging
python -m pytest tests/integration_new_experiment.py::TestNewExperiment::test_new_detected_no_parent -v

# View its log
cat tests/http_test_test_new_detected_no_parent.log
```

## Benefits

✅ **Non-destructive**: Each test gets own log file - no overwrites
✅ **Automatic**: No setup needed - just use `lineage_client` fixture
✅ **Detailed**: Full JSON bodies logged at DEBUG level
✅ **Clean**: INFO level shows just arrows/status, DEBUG shows details
✅ **Persistent**: Logs stay after tests for debugging
✅ **Fast**: Logging adds minimal overhead
✅ **Compatible**: Works with existing test fixtures

## Test Results

**HTTP Integration Tests**: 21/21 passing ✅
- 8/8 NEW strategy tests
- 5/5 RETRY strategy tests
- 5/5 BRANCH strategy tests
- 3/3 HTTP logging demo tests

**Test Suite Overall**: 174 passed, 10 failed
- HTTP logging tests: all passing
- Failures in pre-existing tests (unrelated to logging)

## Next Steps

1. ✅ HTTP logging working
2. ✅ Per-test log files created
3. ✅ Full request/response bodies captured
4. ✅ All HTTP tests passing

### Optional Enhancements (not implemented)
- Add response time logging
- Add request/response size metrics
- Archive old log files weekly
- Create log summary report
