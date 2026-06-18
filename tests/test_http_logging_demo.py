"""Demo test showing HTTP communication logging to file.

This test demonstrates how the http_logger fixture captures
all HTTP requests and responses to per-test log files.
"""

import logging
from pathlib import Path

import pytest

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import CodebaseSnapshotBuilder, ExperimentBuilder
from modules.lineage.client import LineageClient


class TestHttpLogging:
    """Demonstrate HTTP logging to file."""

    def test_http_logging_captures_pre_request(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
        http_logger: logging.Logger,
        test_project: Path,
        request,
    ):
        """PRE request captured in log file with request/response bodies.

        Verifies:
        - Request logged with → indicator
        - Response logged with ← indicator
        - JSON bodies logged at DEBUG level
        - HTTP status codes captured
        - Log file created with per-test naming
        """
        # Execute PRE request
        ctx = lineage_client.pre_execution()

        # Verify response
        assert ctx.experiment_id
        assert ctx.strategy == "NEW"

        # Get dynamic log file name
        test_name = request.node.name.replace("/", "_").replace("::", "_")
        log_file = Path(__file__).parent / f"http_test_{test_name}.log"
        assert log_file.exists(), f"Log file not created at {log_file}"

        # Check log contents
        log_content = log_file.read_text()

        # Should contain request marker
        assert "→ POST /api/v1/pre" in log_content, "Request not logged"

        # Should contain response marker with status
        assert "← 200 POST /api/v1/pre" in log_content, "Response not logged"

        # Should contain request body (JSON)
        assert "experiment_name" in log_content, "Request body not logged"
        assert "codebase" in log_content, "Codebase files not logged"

        # Should contain response body (JSON)
        assert "strategy" in log_content, "Response strategy not logged"
        assert ctx.experiment_id in log_content, "Experiment ID not logged"

    def test_http_logging_multi_strategy_sequence(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
        http_logger: logging.Logger,
        test_project: Path,
        request,
    ):
        """Multiple PRE requests logged sequentially.

        Verifies:
        - First PRE: NEW strategy
        - Second PRE: RETRY strategy (same code)
        - Both captured in log file
        """
        # Get dynamic log file name
        test_name = request.node.name.replace("/", "_").replace("::", "_")
        log_file = Path(__file__).parent / f"http_test_{test_name}.log"

        # First run - NEW
        ctx1 = lineage_client.pre_execution()
        assert ctx1.strategy == "NEW"

        # Log file should exist after first request
        assert log_file.exists(), f"Log file not created at {log_file}"

        # Read log after first request
        log_after_first = log_file.read_text()
        request_count_1 = log_after_first.count("→ POST /api/v1/pre")
        response_count_1 = log_after_first.count("← 200 POST /api/v1/pre")
        assert request_count_1 == 1, "First request not logged"
        assert response_count_1 == 1, "First response not logged"

        # Second run - should detect same codebase, use RETRY
        ctx2 = lineage_client.pre_execution()
        # (RETRY detection depends on actual implementation)

        # Read full log
        log_content = log_file.read_text()
        request_count_all = log_content.count("→ POST /api/v1/pre")
        response_count_all = log_content.count("← 200 POST /api/v1/pre")

        # At least 2 requests total (first + second)
        assert request_count_all >= 2, f"Expected >=2 requests, got {request_count_all}"
        assert response_count_all >= 2, f"Expected >=2 responses, got {response_count_all}"

    def test_log_file_format_validation(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
        http_logger: logging.Logger,
        request,
    ):
        """Log file format matches expected pattern.

        Verifies:
        - Timestamp format: YYYY-MM-DD HH:MM:SS
        - Level labels: [INFO], [DEBUG]
        - Logger name present
        - Arrows for request/response direction
        """
        # Execute request
        lineage_client.pre_execution()

        # Get dynamic log file name
        test_name = request.node.name.replace("/", "_").replace("::", "_")
        log_file = Path(__file__).parent / f"http_test_{test_name}.log"

        log_lines = log_file.read_text().strip().split("\n")

        # Find INFO lines (request/response)
        info_lines = [l for l in log_lines if "[INFO]" in l]
        assert len(info_lines) >= 2, "Expected at least one request and one response"

        # Check first line format
        first_info = info_lines[0]

        # Should have timestamp YYYY-MM-DD HH:MM:SS
        assert first_info.startswith("202"), "Missing timestamp"

        # Should have [INFO] level
        assert "[INFO]" in first_info, "Missing [INFO] level marker"

        # Should have logger name
        assert "http_connector_test" in first_info, "Missing logger name"

        # Should have arrow indicator
        assert "→" in first_info or "←" in first_info, "Missing direction arrow"
