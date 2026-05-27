"""Tests for HTTP connector (Phase 6.3): real httpx calls against a mock transport."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from modules.lineage.config import ServerConfig
from modules.lineage.connector import ConnectorFactory, ServerError
from modules.lineage.http_connector import HttpConnector
from modules.lineage.models import (
    HealthResponse,
    PostRequest,
    PostResponse,
    PreRequest,
    PreResponse,
)


# ─── MOCK TRANSPORT ───────────────────────────────────────────────────────────


class MockTransport(httpx.BaseTransport):
    """Mock transport that returns predefined responses based on path."""

    def __init__(self, responses: dict[str, tuple[int, dict]] | None = None):
        self._responses = responses or {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self._responses:
            status, body = self._responses[path]
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"detail": "not found"})


class TimeoutTransport(httpx.BaseTransport):
    """Transport that always raises a timeout."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("read timed out")


class ConnectErrorTransport(httpx.BaseTransport):
    """Transport that simulates connection refused."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")


# ─── HELPER ────────────────────────────────────────────────────────────────────


def _make_connector(transport: httpx.BaseTransport) -> HttpConnector:
    """Create HttpConnector with a custom transport (bypasses real network)."""
    config = ServerConfig(url="http://testserver:8000", protocol="http", timeout=5)
    connector = HttpConnector(config)
    # Replace the internal client with one using our mock transport
    connector._client = httpx.Client(base_url="http://testserver:8000", transport=transport)
    return connector


# ─── TESTS ─────────────────────────────────────────────────────────────────────


class TestHttpConnectorHealth:
    def test_health_success(self):
        transport = MockTransport({
            "/health": (200, {"status": "ok", "version": "0.1.0", "neo4j_connected": True}),
        })
        connector = _make_connector(transport)
        resp = connector.health()
        assert resp.status == "ok"
        assert resp.neo4j_connected is True
        connector.close()

    def test_health_connection_error(self):
        connector = _make_connector(ConnectErrorTransport())
        with pytest.raises(ConnectionError, match="Cannot reach"):
            connector.health()
        connector.close()

    def test_health_timeout(self):
        connector = _make_connector(TimeoutTransport())
        with pytest.raises(ConnectionError, match="timeout"):
            connector.health()
        connector.close()


class TestHttpConnectorPre:
    def test_send_pre_success(self):
        pre_response = {
            "experiment_id": "exp-http-001",
            "strategy": "BRANCH",
            "base": False,
            "description": "Branch from parent",
            "changed_files": ["train.py"],
            "base_experiment_id": "base-001",
            "previous_experiment_id": "prev-001",
        }
        transport = MockTransport({"/api/v1/pre": (200, pre_response)})
        connector = _make_connector(transport)

        req = PreRequest(
            experiment_name="test",
            experiment_uri="/home/user/project",
            codebase={"train.py": "import torch"},
        )
        resp = connector.send_pre(req)

        assert resp.experiment_id == "exp-http-001"
        assert resp.strategy == "BRANCH"
        assert resp.changed_files == ["train.py"]
        connector.close()

    def test_send_pre_server_error(self):
        transport = MockTransport({
            "/api/v1/pre": (422, {"detail": "model_uri required"}),
        })
        connector = _make_connector(transport)

        req = PreRequest(experiment_name="test", codebase={})
        with pytest.raises(ServerError) as exc_info:
            connector.send_pre(req)
        assert exc_info.value.status_code == 422
        assert "model_uri" in exc_info.value.detail
        connector.close()

    def test_send_pre_connection_refused(self):
        connector = _make_connector(ConnectErrorTransport())
        req = PreRequest(experiment_name="test", codebase={})
        with pytest.raises(ConnectionError):
            connector.send_pre(req)
        connector.close()

    def test_send_pre_timeout(self):
        connector = _make_connector(TimeoutTransport())
        req = PreRequest(experiment_name="test", codebase={})
        with pytest.raises(ConnectionError, match="timeout"):
            connector.send_pre(req)
        connector.close()


class TestHttpConnectorPost:
    def test_send_post_success(self):
        post_response = {
            "experiment_id": "exp-001",
            "status": "COMPLETED",
            "acknowledged": True,
        }
        transport = MockTransport({"/api/v1/post": (200, post_response)})
        connector = _make_connector(transport)

        req = PostRequest(experiment_id="exp-001", status="COMPLETED")
        resp = connector.send_post(req)

        assert resp.experiment_id == "exp-001"
        assert resp.acknowledged is True
        connector.close()

    def test_send_post_failure_status(self):
        transport = MockTransport({
            "/api/v1/post": (404, {"detail": "experiment not found"}),
        })
        connector = _make_connector(transport)

        req = PostRequest(experiment_id="unknown", status="COMPLETED")
        with pytest.raises(ServerError) as exc_info:
            connector.send_post(req)
        assert exc_info.value.status_code == 404
        connector.close()

    def test_send_post_connection_error(self):
        connector = _make_connector(ConnectErrorTransport())
        req = PostRequest(experiment_id="exp-001", status="FAILED")
        with pytest.raises(ConnectionError):
            connector.send_post(req)
        connector.close()


class TestHttpConnectorAutoRegister:
    def test_factory_creates_http_connector(self):
        # http_connector module auto-registers on import, but our test_client_sdk
        # clears the registry. Re-import to verify registration works.
        ConnectorFactory._registry.clear()
        # Re-trigger registration
        import importlib
        import modules.lineage.http_connector as hc
        importlib.reload(hc)

        config = ServerConfig(url="http://localhost:8000", protocol="http")
        connector = ConnectorFactory.create(config)
        assert type(connector).__name__ == "HttpConnector"
        connector.close()
