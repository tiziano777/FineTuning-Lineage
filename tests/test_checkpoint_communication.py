"""Tests for checkpoint communication: server endpoint + callback + decorator injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from graph_lineage.server.app import app
from graph_lineage.server.schemas import CheckpointRequest, CheckpointResponse


# ── Server endpoint tests ─────────────────────────────────────────────────────


class TestCheckpointEndpoint:
    """Tests for POST /api/v1/checkpoint."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @patch("graph_lineage.server.app.create_checkpoint_edge")
    @patch("graph_lineage.server.app.create_checkpoint_node")
    def test_creates_checkpoint_and_edge(self, mock_create_node, mock_create_edge, client):
        """Endpoint creates checkpoint node and PRODUCED edge."""
        mock_create_node.return_value = "ckp-uuid-123"

        payload = {
            "experiment_id": "exp-001",
            "name": "checkpoint-500",
            "epoch": 1,
            "run": 1,
            "uri": "/output/checkpoint-500",
            "metrics": {"loss": 0.25},
            "derived_from": "llama-3",
            "is_merging": False,
        }

        resp = client.post("/api/v1/checkpoint", json=payload)
        assert resp.status_code == 200

        data = resp.json()
        assert data["experiment_id"] == "exp-001"
        assert data["acknowledged"] is True
        assert "checkpoint_id" in data

        # Verify node was created
        mock_create_node.assert_called_once()
        ckp_arg = mock_create_node.call_args[0][0]
        assert ckp_arg.name == "checkpoint-500"
        assert ckp_arg.epoch == 1
        assert ckp_arg.run == 1
        assert ckp_arg.uri == "/output/checkpoint-500"
        assert ckp_arg.metrics == {"loss": 0.25}
        assert ckp_arg.derived_from == "llama-3"

        # Verify edge was created
        mock_create_edge.assert_called_once()

    @patch("graph_lineage.server.app.create_checkpoint_edge")
    @patch("graph_lineage.server.app.create_checkpoint_node")
    def test_minimal_payload(self, mock_create_node, mock_create_edge, client):
        """Endpoint works with minimal required fields."""
        mock_create_node.return_value = "ckp-uuid-456"

        payload = {
            "experiment_id": "exp-002",
            "name": "ckp-100",
            "epoch": 0,
            "run": 1,
            "uri": "/tmp/ckp",
        }

        resp = client.post("/api/v1/checkpoint", json=payload)
        assert resp.status_code == 200

        ckp_arg = mock_create_node.call_args[0][0]
        assert ckp_arg.metrics == {}
        assert ckp_arg.derived_from == ""
        assert ckp_arg.is_merging is False

    @patch("graph_lineage.server.app.create_checkpoint_node", side_effect=RuntimeError("DB down"))
    def test_server_error_returns_500(self, mock_create_node, client):
        """Server returns 500 on internal error."""
        payload = {
            "experiment_id": "exp-003",
            "name": "ckp-fail",
            "epoch": 0,
            "run": 1,
            "uri": "/tmp/fail",
        }

        resp = client.post("/api/v1/checkpoint", json=payload)
        assert resp.status_code == 500


# ── Callback tests ────────────────────────────────────────────────────────────


class TestLineageCheckpointCallback:
    """Tests for LineageCheckpointCallback.on_save()."""

    @pytest.fixture
    def mock_ctx(self):
        from graph_lineage.setups._base.modules.lineage.client import ExecutionContext
        from graph_lineage.setups._base.modules.lineage.config import ServerConfig
        from pathlib import Path

        config = ServerConfig(url="http://localhost:8000", protocol="http", timeout=10, retries=1, blocking=False)
        return ExecutionContext(
            experiment_id="exp-test",
            strategy="NEW",
            project_root=Path("/tmp/project"),
            server_config=config,
            extra={"model_id": "llama-3"},
        )

    @patch("graph_lineage.setups._base.modules.lineage.callbacks.ConnectorFactory.create")
    def test_on_save_sends_checkpoint(self, mock_factory, mock_ctx):
        """on_save sends CheckpointRequest to connector."""
        from graph_lineage.setups._base.modules.lineage.callbacks import LineageCheckpointCallback
        from graph_lineage.setups._base.modules.lineage.models import CheckpointResponse

        mock_connector = MagicMock()
        mock_connector.send_checkpoint.return_value = CheckpointResponse(
            checkpoint_id="ckp-resp-1", experiment_id="exp-test"
        )
        mock_factory.return_value = mock_connector

        callback = LineageCheckpointCallback(ctx=mock_ctx)

        # Simulate TrainerState and args
        state = MagicMock()
        state.best_model_checkpoint = "/output/checkpoint-100"
        state.epoch = 2
        state.log_history = [{"loss": 0.3, "epoch": 2.0}]

        args = MagicMock()
        args.output_dir = "/output"

        callback.on_save(args=args, state=state, control=None)

        mock_connector.send_checkpoint.assert_called_once()
        req = mock_connector.send_checkpoint.call_args[0][0]
        assert req.experiment_id == "exp-test"
        assert req.name == "checkpoint-100"
        assert req.epoch == 2
        assert req.run == 1
        assert req.metrics == {"loss": 0.3, "epoch": 2.0}
        assert req.derived_from == "llama-3"

    @patch("graph_lineage.setups._base.modules.lineage.callbacks.ConnectorFactory.create")
    def test_on_save_non_blocking_swallows_error(self, mock_factory, mock_ctx):
        """Non-blocking mode logs warning instead of raising."""
        from graph_lineage.setups._base.modules.lineage.callbacks import LineageCheckpointCallback

        mock_connector = MagicMock()
        mock_connector.send_checkpoint.side_effect = ConnectionError("timeout")
        mock_factory.return_value = mock_connector

        callback = LineageCheckpointCallback(ctx=mock_ctx, blocking=False)

        state = MagicMock()
        state.best_model_checkpoint = None
        state.epoch = 1
        state.log_history = []

        args = MagicMock()
        args.output_dir = "/output/run"

        # Should NOT raise
        callback.on_save(args=args, state=state, control=None)

    @patch("graph_lineage.setups._base.modules.lineage.callbacks.ConnectorFactory.create")
    def test_on_save_blocking_raises(self, mock_factory, mock_ctx):
        """Blocking mode re-raises connection errors."""
        from graph_lineage.setups._base.modules.lineage.callbacks import LineageCheckpointCallback

        mock_connector = MagicMock()
        mock_connector.send_checkpoint.side_effect = ConnectionError("timeout")
        mock_factory.return_value = mock_connector

        callback = LineageCheckpointCallback(ctx=mock_ctx, blocking=True)

        state = MagicMock()
        state.best_model_checkpoint = "/output/ckp"
        state.epoch = 1
        state.log_history = []

        args = MagicMock()
        args.output_dir = "/output"

        with pytest.raises(ConnectionError):
            callback.on_save(args=args, state=state, control=None)

    @patch("graph_lineage.setups._base.modules.lineage.callbacks.ConnectorFactory.create")
    def test_run_counter_increments(self, mock_factory, mock_ctx):
        """Each on_save increments the run counter."""
        from graph_lineage.setups._base.modules.lineage.callbacks import LineageCheckpointCallback
        from graph_lineage.setups._base.modules.lineage.models import CheckpointResponse

        mock_connector = MagicMock()
        mock_connector.send_checkpoint.return_value = CheckpointResponse(
            checkpoint_id="ckp-1", experiment_id="exp-test"
        )
        mock_factory.return_value = mock_connector

        callback = LineageCheckpointCallback(ctx=mock_ctx)

        state = MagicMock()
        state.best_model_checkpoint = "/output/ckp"
        state.epoch = 1
        state.log_history = [{}]
        args = MagicMock()
        args.output_dir = "/output"

        callback.on_save(args=args, state=state, control=None)
        callback.on_save(args=args, state=state, control=None)

        calls = mock_connector.send_checkpoint.call_args_list
        assert calls[0][0][0].run == 1
        assert calls[1][0][0].run == 2


# ── Decorator injection test ──────────────────────────────────────────────────


class TestDecoratorInjection:
    """Tests that lineage_tracker(capture_checkpoints=True) injects the callback."""

    @patch("graph_lineage.setups._base.modules.lineage.LineageClient")
    @patch("graph_lineage.setups._base.modules.lineage.callbacks.ConnectorFactory.create")
    def test_callback_injected_when_capture_checkpoints(self, mock_factory, mock_client_cls):
        """Decorator injects lineage_callback kwarg when capture_checkpoints=True."""
        from graph_lineage.setups._base.modules.lineage import lineage_tracker
        from graph_lineage.setups._base.modules.lineage.client import ExecutionContext
        from graph_lineage.setups._base.modules.lineage.config import ServerConfig
        from pathlib import Path

        config = ServerConfig(url="http://localhost:8000", protocol="http", timeout=10, retries=1, blocking=False)
        mock_ctx = ExecutionContext(
            experiment_id="exp-inj",
            strategy="NEW",
            project_root=Path("/tmp"),
            server_config=config,
            extra={"model_id": "test-model"},
        )

        mock_instance = MagicMock()
        mock_instance.pre_execution.return_value = mock_ctx
        mock_client_cls.return_value = mock_instance

        mock_connector = MagicMock()
        mock_factory.return_value = mock_connector

        received_callback = {}

        @lineage_tracker(capture_checkpoints=True)
        def train(config_path: str, lineage_callback=None):
            received_callback["cb"] = lineage_callback
            return "done"

        result = train("/tmp/config.yml")
        assert result == "done"
        assert received_callback["cb"] is not None
        # Verify it's a LineageCheckpointCallback instance (duck-type check)
        assert hasattr(received_callback["cb"], "on_save")
