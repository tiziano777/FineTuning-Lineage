"""Integration tests (Phase 6.5): Client SDK ↔ Server E2E with mocked Neo4j.

These tests spin up the real FastAPI server (via httpx transport mock),
connect the real HTTP connector to it, and verify the full lifecycle works
end-to-end without actual Neo4j.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.server.app import app
from modules.lineage.client import LineageClient
from modules.lineage.config import ServerConfig
from modules.lineage.connector import ConnectorFactory
from modules.lineage.http_connector import HttpConnector


# ─── FIXTURES ──────────────────────────────────────────────────────────────────


class FastAPITransport(httpx.BaseTransport):
    """Transport that routes requests to the FastAPI TestClient (no network)."""

    def __init__(self):
        self._test_client = TestClient(app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # Convert httpx request to TestClient call
        path = request.url.path
        headers = dict(request.headers)
        content = request.content

        if request.method == "GET":
            resp = self._test_client.get(path, headers=headers)
        elif request.method == "POST":
            resp = self._test_client.post(path, content=content, headers=headers)
        else:
            resp = self._test_client.request(request.method, path, content=content, headers=headers)

        return httpx.Response(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
        )


class IntegrationHttpConnector(HttpConnector):
    """HttpConnector that uses FastAPITransport instead of real network."""

    def __init__(self, config: ServerConfig):
        self._config = config
        self._base_url = config.url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base_url,
            transport=FastAPITransport(),
        )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a full project structure for E2E testing."""
    lineage = tmp_path / ".lineage"
    lineage.mkdir()
    (lineage / "server.yml").write_text(
        "url: http://localhost:8000\nprotocol: http\ntimeout: 10\nretries: 0\nblocking: true\n"
    )
    (lineage / "experiment.yml").write_text(yaml.dump({
        "experiment": {
            "id": None,
            "previous_experiment_id": None,
            "base_experiment_id": None,
            "base": True,
            "name": "e2e-test",
            "description": None,
            "uri": None,
            "status": None,
            "checkpoint_resume_from": None,
        }
    }))
    (tmp_path / "train.py").write_text("import torch\n\ndef train():\n    pass\n")
    (tmp_path / "config.yml").write_text("model:\n  name: llama-7b\n  lr: 1e-4\n")
    (tmp_path / "requirements.txt").write_text("torch>=2.0\ntransformers\n")

    modules = tmp_path / "modules" / "utils"
    modules.mkdir(parents=True)
    (modules / "helper.py").write_text("def load_data():\n    return []\n")
    return tmp_path


@pytest.fixture(autouse=True)
def register_integration_connector():
    """Replace http connector with our integration version."""
    ConnectorFactory._registry.clear()
    ConnectorFactory.register("http", IntegrationHttpConnector)
    yield
    ConnectorFactory._registry.clear()


# ─── E2E TESTS ─────────────────────────────────────────────────────────────────


class TestE2ENewExperiment:
    """Full lifecycle for a brand new experiment (no parent)."""

    @patch("graph_lineage.server.app.update_experiment_status")
    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_new_experiment_lifecycle(self, mock_find, mock_create, mock_edge, mock_update, project):
        """Client sends PRE (new) → server creates → client sends POST → done."""
        mock_find.return_value = None
        mock_create.return_value = "new-id"

        client = LineageClient(project_root=project)

        # PRE
        ctx = client.pre_execution()
        assert ctx is not None
        assert ctx.strategy == "NEW"
        assert ctx.experiment_id  # UUID from server

        # Verify experiment node was created with correct codebase
        call_args = mock_create.call_args[0][0]
        assert isinstance(call_args, Experiment)
        assert "train.py" in call_args.codebase
        assert "config.yml" in call_args.codebase
        assert "modules/utils/helper.py" in call_args.codebase
        assert call_args.status == "RUNNING"
        assert call_args.base is True

        # Local state updated
        with open(project / ".lineage" / "experiment.yml") as f:
            local_data = yaml.safe_load(f)["experiment"]
        assert local_data["id"] == ctx.experiment_id
        assert local_data["status"] == "RUNNING"

        # POST
        client.post_execution(ctx, status="COMPLETED", metrics_uri="/logs/m.json")

        with open(project / ".lineage" / "experiment.yml") as f:
            local_data = yaml.safe_load(f)["experiment"]
        assert local_data["status"] == "COMPLETED"

        client.close()


class TestE2EBranchExperiment:
    """Full lifecycle for a BRANCH (codebase changed)."""

    @patch("graph_lineage.server.app.update_experiment_status")
    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_branch_lifecycle(self, mock_find, mock_create, mock_edge, mock_update, project):
        """Changed train.py → server detects BRANCH strategy."""
        # Parent had different code
        parent = Experiment(
            id="parent-001",
            uri=str(project),
            strategy="NEW",
            base=True,
            model_uri="placeholder",
            model_id="placeholder",
            codebase={
                "train.py": "import torch\n\ndef train():\n    old_code\n",
                "config.yml": "model:\n  name: llama-7b\n  lr: 1e-4\n",
                "requirements.txt": "torch>=2.0\ntransformers\n",
                "modules/utils/helper.py": "def load_data():\n    return []\n",
            },
        )
        mock_find.return_value = parent
        mock_create.return_value = "branch-id"

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()

        assert ctx is not None
        assert ctx.strategy == "BRANCH"

        # Edge should be created
        mock_edge.assert_called_once()
        edge_call = mock_edge.call_args
        assert edge_call[0][2] == "DERIVED_FROM"  # rel_type

        client.close()


class TestE2ERetryExperiment:
    """Full lifecycle for a RETRY (same codebase as parent)."""

    @patch("graph_lineage.server.app.update_experiment_status")
    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_retry_lifecycle(self, mock_find, mock_create, mock_edge, mock_update, project):
        """Same codebase → server detects RETRY strategy."""
        # Parent has exact same codebase
        # We need to read what capture_codebase would produce for this project
        from modules.lineage.snapshot import capture_codebase
        codebase = capture_codebase(project)

        parent = Experiment(
            id="parent-001",
            uri=str(project),
            strategy="NEW",
            base=True,
            model_uri="placeholder",
            model_id="placeholder",
            codebase=codebase,
        )
        mock_find.return_value = parent
        mock_create.return_value = "retry-id"

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()

        assert ctx is not None
        assert ctx.strategy == "RETRY"

        # RETRY edge should be created
        mock_edge.assert_called_once()
        edge_call = mock_edge.call_args
        assert edge_call[0][2] == "RETRY_OF"

        client.close()


class TestE2EFailedTraining:
    """Client reports FAILED status after training crash."""

    @patch("graph_lineage.server.app.update_experiment_status")
    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_failed_lifecycle(self, mock_find, mock_create, mock_edge, mock_update, project):
        mock_find.return_value = None
        mock_create.return_value = "fail-id"

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()
        assert ctx is not None

        # Simulate training failure
        client.post_execution(ctx, status="FAILED", exit_message="CUDA OOM")

        mock_update.assert_called_once_with(
            exp_id=ctx.experiment_id,
            status="FAILED",
            exit_msg="CUDA OOM",
        )

        with open(project / ".lineage" / "experiment.yml") as f:
            local_data = yaml.safe_load(f)["experiment"]
        assert local_data["status"] == "FAILED"

        client.close()


class TestE2EDecoratorFlow:
    """Full decorator flow: @lineage_tracker wraps function E2E."""

    @patch("graph_lineage.server.app.update_experiment_status")
    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_decorator_e2e(self, mock_find, mock_create, mock_edge, mock_update, project):
        mock_find.return_value = None
        mock_create.return_value = "deco-id"

        from modules.lineage import lineage_tracker

        config_path = str(project / "config.yml")

        @lineage_tracker()
        def my_train(config_path: str):
            return "success"

        result = my_train(config_path=config_path)
        assert result == "success"

        # Verify full lifecycle happened
        mock_create.assert_called_once()
        mock_update.assert_called_once()

        with open(project / ".lineage" / "experiment.yml") as f:
            local_data = yaml.safe_load(f)["experiment"]
        assert local_data["status"] == "COMPLETED"
