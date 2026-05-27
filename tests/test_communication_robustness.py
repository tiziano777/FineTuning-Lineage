"""Robustness tests for client-server communication.

Tests edge cases, failure modes, retry logic, large payloads,
malformed responses, partial failures, and concurrent behavior.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from modules.lineage.client import LineageClient, LineageClientError, _find_project_root
from modules.lineage.config import ServerConfig
from modules.lineage.connector import ConnectorFactory, ServerError
from modules.lineage.http_connector import HttpConnector
from modules.lineage.models import PostRequest, PreRequest


# ─── TRANSPORTS ────────────────────────────────────────────────────────────────


class FlakeyTransport(httpx.BaseTransport):
    """Fails N times then succeeds on attempt N+1."""

    def __init__(self, fail_count: int, success_response: dict, status: int = 200):
        self._fail_count = fail_count
        self._attempts = 0
        self._success_response = success_response
        self._status = status

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise httpx.ConnectError("Connection refused")
        return httpx.Response(self._status, json=self._success_response)

    @property
    def attempts(self) -> int:
        return self._attempts


class SlowTransport(httpx.BaseTransport):
    """Responds after a configurable delay."""

    def __init__(self, delay_seconds: float, response: dict, status: int = 200):
        self._delay = delay_seconds
        self._response = response
        self._status = status

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        time.sleep(self._delay)
        return httpx.Response(self._status, json=self._response)


class MalformedResponseTransport(httpx.BaseTransport):
    """Returns invalid JSON or unexpected structure."""

    def __init__(self, raw_body: bytes, status: int = 200):
        self._raw_body = raw_body
        self._status = status

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            self._status,
            content=self._raw_body,
            headers={"content-type": "application/json"},
        )


class StatusToggleTransport(httpx.BaseTransport):
    """Returns different status on PRE vs POST paths."""

    def __init__(self, pre_response: tuple[int, dict], post_response: tuple[int, dict]):
        self._pre = pre_response
        self._post = post_response

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/pre" in path:
            return httpx.Response(self._pre[0], json=self._pre[1])
        elif "/post" in path:
            return httpx.Response(self._post[0], json=self._post[1])
        elif "/health" in path:
            return httpx.Response(200, json={"status": "ok", "version": "0.1.0", "neo4j_connected": True})
        return httpx.Response(404, json={"detail": "not found"})


class RequestCapturingTransport(httpx.BaseTransport):
    """Captures all requests for inspection, returns canned response."""

    def __init__(self, response: dict, status: int = 200):
        self._response = response
        self._status = status
        self.captured_requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_requests.append(request)
        return httpx.Response(self._status, json=self._response)


# ─── HELPERS ───────────────────────────────────────────────────────────────────


def _make_connector(transport: httpx.BaseTransport, retries: int = 3, timeout: int = 5) -> HttpConnector:
    config = ServerConfig(url="http://testserver:8000", protocol="http", timeout=timeout, retries=retries)
    connector = HttpConnector(config)
    connector._client = httpx.Client(base_url="http://testserver:8000", transport=transport)
    return connector


def _make_project(tmp_path: Path, blocking: bool = True, retries: int = 3) -> Path:
    """Create a minimal project with .lineage/ config."""
    lineage = tmp_path / ".lineage"
    lineage.mkdir()
    (lineage / "server.yml").write_text(yaml.dump({
        "url": "http://testserver:8000",
        "protocol": "http",
        "timeout": 5,
        "retries": retries,
        "blocking": blocking,
    }))
    (lineage / "experiment.yml").write_text(yaml.dump({
        "experiment": {
            "id": None,
            "name": "robustness-test",
            "uri": str(tmp_path),
            "base": True,
            "previous_experiment_id": None,
            "base_experiment_id": None,
            "status": None,
            "description": None,
            "checkpoint_resume_from": None,
        }
    }))
    (tmp_path / "train.py").write_text("def train(): pass\n")
    (tmp_path / "config.yml").write_text("model:\n  name: test\n")
    return tmp_path


# ─── RETRY LOGIC TESTS ────────────────────────────────────────────────────────


class TestRetryBehavior:
    """Verify exponential backoff retry logic."""

    @patch("time.sleep")  # Skip actual waiting
    def test_retry_succeeds_after_failures(self, mock_sleep):
        """Client retries on ConnectionError and succeeds when server recovers."""
        pre_response = {
            "experiment_id": "retry-ok",
            "strategy": "NEW",
            "base": True,
            "description": "auto",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }
        transport = FlakeyTransport(fail_count=2, success_response=pre_response)
        config = ServerConfig(url="http://testserver:8000", protocol="http", timeout=5, retries=3)
        connector = HttpConnector(config)
        connector._client = httpx.Client(base_url="http://testserver:8000", transport=transport)

        # Use client's retry logic (not connector's)
        from modules.lineage.client import LineageClient
        client = LineageClient.__new__(LineageClient)
        client._project_root = Path("/tmp")
        client._server_config = config
        client._connector = connector

        req = PreRequest(experiment_name="test", codebase={"train.py": "x"})
        resp = client._retry(lambda: connector.send_pre(req))

        assert resp.experiment_id == "retry-ok"
        assert transport.attempts == 3  # 2 failures + 1 success
        connector.close()

    def test_retry_exhausted_raises(self):
        """After max retries, ConnectionError propagates."""
        transport = FlakeyTransport(fail_count=10, success_response={})
        connector = _make_connector(transport, retries=2)

        req = PreRequest(experiment_name="test", codebase={})
        with pytest.raises(ConnectionError):
            connector.send_pre(req)

        assert transport.attempts == 1  # connector itself doesn't retry, client does
        connector.close()

    @patch("time.sleep")  # Skip actual waiting in tests
    def test_client_retry_with_backoff(self, mock_sleep, tmp_path):
        """LineageClient._retry uses exponential backoff."""
        pre_response = {
            "experiment_id": "backoff-ok",
            "strategy": "NEW",
            "base": True,
            "description": "auto",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }
        transport = FlakeyTransport(fail_count=2, success_response=pre_response)

        project = _make_project(tmp_path, retries=3)
        ConnectorFactory._registry.clear()

        class TestConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(base_url=config.url, transport=transport)

        ConnectorFactory.register("http", TestConnector)

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()

        assert ctx is not None
        assert ctx.strategy == "NEW"
        # Backoff sleep calls: 2^0=1, 2^1=2
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == 1
        assert mock_sleep.call_args_list[1][0][0] == 2

        ConnectorFactory._registry.clear()
        client.close()


# ─── BLOCKING VS NON-BLOCKING ─────────────────────────────────────────────────


class TestBlockingMode:
    """Blocking=true should sys.exit; blocking=false should return None."""

    def test_blocking_connection_error_exits(self, tmp_path):
        """Server unreachable in blocking mode → sys.exit(10)."""
        project = _make_project(tmp_path, blocking=True, retries=0)
        ConnectorFactory._registry.clear()

        class FailConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))),
                )

        ConnectorFactory.register("http", FailConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 10

        ConnectorFactory._registry.clear()

    def test_nonblocking_connection_error_returns_none(self, tmp_path):
        """Server unreachable in non-blocking mode → returns None, no exit."""
        project = _make_project(tmp_path, blocking=False, retries=0)
        ConnectorFactory._registry.clear()

        class FailConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))),
                )

        ConnectorFactory.register("http", FailConnector)

        client = LineageClient(project_root=project)
        result = client.pre_execution()
        assert result is None

        ConnectorFactory._registry.clear()

    def test_blocking_server_rejection_exits(self, tmp_path):
        """Server returns 4xx in blocking mode → sys.exit(9)."""
        project = _make_project(tmp_path, blocking=True, retries=0)
        ConnectorFactory._registry.clear()

        class RejectConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(
                        lambda r: httpx.Response(422, json={"detail": "invalid config"})
                    ),
                )

        ConnectorFactory.register("http", RejectConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 9

        ConnectorFactory._registry.clear()


# ─── LARGE PAYLOAD TESTS ──────────────────────────────────────────────────────


class TestLargePayloads:
    """Verify behavior with large codebase payloads."""

    def test_large_codebase_sends_successfully(self, tmp_path):
        """Client can send a project with many files (~100)."""
        project = _make_project(tmp_path)
        modules_dir = project / "modules" / "layer"
        modules_dir.mkdir(parents=True)
        for i in range(100):
            (modules_dir / f"module_{i}.py").write_text(f"class Layer{i}:\n    pass\n" * 10)

        pre_response = {
            "experiment_id": "big-001",
            "strategy": "NEW",
            "base": True,
            "description": "auto",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }
        capturing = RequestCapturingTransport(pre_response)
        ConnectorFactory._registry.clear()

        class CapturingConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(base_url=config.url, transport=capturing)

        ConnectorFactory.register("http", CapturingConnector)

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()

        assert ctx is not None
        assert ctx.experiment_id == "big-001"

        # Verify the request body contains all 100 module files
        body = json.loads(capturing.captured_requests[0].content)
        module_files = [k for k in body["codebase"] if k.startswith("modules/")]
        assert len(module_files) == 100

        ConnectorFactory._registry.clear()
        client.close()

    def test_file_too_large_exits(self, tmp_path):
        """File > 10MB triggers FileTooLargeError → sys.exit(8)."""
        project = _make_project(tmp_path)
        # Create a >10MB file
        big_file = project / "huge_data.py"
        big_file.write_text("x" * (11 * 1024 * 1024))  # 11MB

        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", HttpConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 8

        ConnectorFactory._registry.clear()


# ─── MALFORMED RESPONSE TESTS ─────────────────────────────────────────────────


class TestMalformedResponses:
    """Server returns unexpected data — client should handle gracefully."""

    def test_invalid_json_response(self, tmp_path):
        """Server returns non-JSON → client errors in blocking mode."""
        project = _make_project(tmp_path, blocking=True, retries=0)
        ConnectorFactory._registry.clear()

        class GarbageConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=MalformedResponseTransport(b"not json at all{{{", status=200),
                )

        ConnectorFactory.register("http", GarbageConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        # Generic PRE error (malformed response = unexpected exception)
        assert exc_info.value.code == 4

        ConnectorFactory._registry.clear()

    def test_missing_fields_in_response(self, tmp_path):
        """Server returns 200 but response missing required fields."""
        project = _make_project(tmp_path, blocking=True, retries=0)
        ConnectorFactory._registry.clear()

        class PartialConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                # Response missing experiment_id
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(
                        lambda r: httpx.Response(200, json={"strategy": "NEW"})
                    ),
                )

        ConnectorFactory.register("http", PartialConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 4

        ConnectorFactory._registry.clear()


# ─── POST-EXECUTION FAILURE ISOLATION ──────────────────────────────────────────


class TestPostExecutionIsolation:
    """POST failures must never crash — training result is sacred."""

    def test_post_failure_does_not_raise(self, tmp_path):
        """POST error is swallowed — function returns normally."""
        project = _make_project(tmp_path, retries=0)

        pre_response = {
            "experiment_id": "post-fail",
            "strategy": "NEW",
            "base": True,
            "description": "auto",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }
        post_error = {"detail": "internal server error"}

        ConnectorFactory._registry.clear()

        class SplitConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=StatusToggleTransport(
                        pre_response=(200, pre_response),
                        post_response=(500, post_error),
                    ),
                )

        ConnectorFactory.register("http", SplitConnector)

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()
        assert ctx is not None

        # POST should NOT raise even though server returns 500
        client.post_execution(ctx, status="COMPLETED")

        ConnectorFactory._registry.clear()
        client.close()

    def test_post_connection_lost_does_not_raise(self, tmp_path):
        """POST with connection lost — no propagation."""
        project = _make_project(tmp_path, retries=0)

        pre_response = {
            "experiment_id": "post-lost",
            "strategy": "NEW",
            "base": True,
            "description": "auto",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }

        call_count = {"n": 0}

        class DisconnectOnPostTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                call_count["n"] += 1
                if "/post" in request.url.path:
                    raise httpx.ConnectError("server went away")
                return httpx.Response(200, json=pre_response)

        ConnectorFactory._registry.clear()

        class DisconnectConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=DisconnectOnPostTransport(),
                )

        ConnectorFactory.register("http", DisconnectConnector)

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()
        assert ctx is not None

        # Should not raise
        client.post_execution(ctx, status="COMPLETED")

        ConnectorFactory._registry.clear()
        client.close()


# ─── LOCAL STATE CONSISTENCY ───────────────────────────────────────────────────


class TestLocalStateConsistency:
    """Verify .lineage/experiment.yml stays consistent across scenarios."""

    def test_pre_updates_local_id(self, tmp_path):
        """After PRE, local experiment.yml has the server-assigned ID."""
        project = _make_project(tmp_path, retries=0)
        pre_response = {
            "experiment_id": "server-assigned-uuid",
            "strategy": "NEW",
            "base": True,
            "description": "First run",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }
        ConnectorFactory._registry.clear()

        class OkConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(lambda r: httpx.Response(200, json=pre_response)),
                )

        ConnectorFactory.register("http", OkConnector)

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()

        with open(project / ".lineage" / "experiment.yml") as f:
            data = yaml.safe_load(f)["experiment"]
        assert data["id"] == "server-assigned-uuid"
        assert data["status"] == "RUNNING"
        assert data["base"] is True

        ConnectorFactory._registry.clear()
        client.close()

    def test_post_updates_local_status(self, tmp_path):
        """After POST, local experiment.yml has COMPLETED status."""
        project = _make_project(tmp_path, retries=0)
        pre_response = {
            "experiment_id": "state-test",
            "strategy": "NEW",
            "base": True,
            "description": "auto",
            "changed_files": [],
            "base_experiment_id": None,
            "previous_experiment_id": None,
        }
        post_response = {
            "experiment_id": "state-test",
            "status": "COMPLETED",
            "acknowledged": True,
        }
        ConnectorFactory._registry.clear()

        class StateConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=StatusToggleTransport(
                        pre_response=(200, pre_response),
                        post_response=(200, post_response),
                    ),
                )

        ConnectorFactory.register("http", StateConnector)

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()
        client.post_execution(ctx, status="COMPLETED")

        with open(project / ".lineage" / "experiment.yml") as f:
            data = yaml.safe_load(f)["experiment"]
        assert data["status"] == "COMPLETED"

        ConnectorFactory._registry.clear()
        client.close()

    def test_failed_pre_leaves_local_state_untouched(self, tmp_path):
        """If PRE fails, .lineage/experiment.yml is not modified."""
        project = _make_project(tmp_path, blocking=False, retries=0)

        # Read original state
        with open(project / ".lineage" / "experiment.yml") as f:
            original = f.read()

        ConnectorFactory._registry.clear()

        class FailConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("fail"))),
                )

        ConnectorFactory.register("http", FailConnector)

        client = LineageClient(project_root=project)
        result = client.pre_execution()
        assert result is None

        # State unchanged
        with open(project / ".lineage" / "experiment.yml") as f:
            after = f.read()
        assert after == original

        ConnectorFactory._registry.clear()


# ─── PROJECT ROOT DETECTION ────────────────────────────────────────────────────


class TestProjectRootDetection:
    """Test .lineage/ directory discovery."""

    def test_find_root_from_subdir(self, tmp_path):
        """Walking up from nested dir finds .lineage/ at project root."""
        (tmp_path / ".lineage").mkdir()
        nested = tmp_path / "src" / "models"
        nested.mkdir(parents=True)

        root = _find_project_root(nested)
        assert root == tmp_path.resolve()

    def test_no_lineage_dir_raises(self, tmp_path):
        """No .lineage/ anywhere → LineageClientError."""
        nested = tmp_path / "deep" / "nested"
        nested.mkdir(parents=True)

        with pytest.raises(LineageClientError, match="No .lineage/ directory"):
            _find_project_root(nested)


# ─── SERVER ERROR CODE MAPPING ─────────────────────────────────────────────────


class TestServerErrorCodes:
    """Verify different HTTP error codes produce correct exit behavior."""

    @pytest.mark.parametrize("status_code,detail", [
        (409, "ModelIdMismatchError: model changed"),
        (422, "base_experiment_id 'abc' not found"),
        (500, "Internal server error"),
    ])
    def test_server_error_codes_exit_9(self, tmp_path, status_code, detail):
        """Any server rejection (4xx/5xx) in blocking mode → exit 9."""
        project = _make_project(tmp_path, blocking=True, retries=0)
        ConnectorFactory._registry.clear()

        class ErrorConnector(HttpConnector):
            def __init__(self, config):
                super().__init__(config)
                self._client = httpx.Client(
                    base_url=config.url,
                    transport=httpx.MockTransport(
                        lambda r: httpx.Response(status_code, json={"detail": detail})
                    ),
                )

        ConnectorFactory.register("http", ErrorConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 9

        ConnectorFactory._registry.clear()
