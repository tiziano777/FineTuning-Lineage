"""Tests for Lineage Server API (Phase 6.4): FastAPI endpoints with mocked Neo4j."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.server.app import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


# ─── HEALTH TESTS ──────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_with_neo4j_down(self, client):
        """Health returns degraded when Neo4j is unavailable."""
        with patch("graph_lineage.neo4j_client.client.get_driver", side_effect=Exception("no neo4j")):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["neo4j_connected"] is False
        assert "version" in data


# ─── PRE-EXECUTION TESTS ──────────────────────────────────────────────────────


class TestPreEndpoint:
    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_pre_new_experiment(self, mock_find_parent, mock_create, mock_edge, client):
        """First experiment (no parent) → strategy=NEW."""
        mock_find_parent.return_value = None
        mock_create.return_value = "new-id"

        payload = {
            "experiment_name": "sft-train",
            "experiment_uri": "/home/user/project",
            "codebase": {"train.py": "import torch", "config.yml": "model: llama"},
        }
        resp = client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "NEW"
        assert data["base"] is True
        assert data["experiment_id"]  # UUID assigned
        assert "experiment" in data["description"].lower() or "new" in data["description"].lower()

        # Verify Neo4j was called
        mock_create.assert_called_once()
        mock_edge.assert_not_called()  # NEW has no edge

    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_pre_branch_experiment(self, mock_find_parent, mock_create, mock_edge, client):
        """Changed codebase from parent → strategy=BRANCH."""
        parent = Experiment(
            id="parent-001",
            uri="/home/user/project",
            strategy="NEW",
            base=True,
            model_uri="/nfs/llama",
            model_id="llama-7b",
            codebase={"train.py": "import torch", "config.yml": "model: llama"},
        )
        mock_find_parent.return_value = parent
        mock_create.return_value = "branch-id"

        payload = {
            "experiment_name": "sft-train-v2",
            "experiment_uri": "/home/user/project",
            "model_uri": "/nfs/llama",
            "model_id": "llama-7b",
            "codebase": {"train.py": "import torch\ntorch.train()", "config.yml": "model: llama"},
        }
        resp = client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "BRANCH"
        assert data["base"] is False
        assert "train.py" in data["changed_files"]
        mock_edge.assert_called_once()

    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_pre_retry_experiment(self, mock_find_parent, mock_create, mock_edge, client):
        """Same codebase as parent → strategy=RETRY."""
        parent = Experiment(
            id="parent-001",
            uri="/home/user/project",
            strategy="NEW",
            base=True,
            model_uri="/nfs/llama",
            model_id="llama-7b",
            codebase={"train.py": "import torch", "config.yml": "model: llama"},
        )
        mock_find_parent.return_value = parent
        mock_create.return_value = "retry-id"

        payload = {
            "experiment_name": "sft-train",
            "experiment_uri": "/home/user/project",
            "model_uri": "/nfs/llama",
            "model_id": "llama-7b",
            "codebase": {"train.py": "import torch", "config.yml": "model: llama"},
        }
        resp = client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "RETRY"

    @patch("graph_lineage.server.app.find_experiment_by_id")
    def test_pre_invalid_base_experiment_id(self, mock_find_by_id, client):
        """Reference to non-existent base_experiment_id → 422."""
        mock_find_by_id.return_value = None

        payload = {
            "experiment_name": "test",
            "base_experiment_id": "nonexistent-id",
            "codebase": {},
        }
        resp = client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 422
        assert "not found" in resp.json()["detail"]

    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_pre_model_id_mismatch_returns_409(self, mock_find_parent, mock_create, client):
        """model_id mismatch → 409 Conflict."""
        parent = Experiment(
            id="parent-001",
            uri="/home/user/project",
            strategy="NEW",
            base=True,
            model_uri="/nfs/llama",
            model_id="llama-7b",
            codebase={"train.py": "code"},
        )
        mock_find_parent.return_value = parent

        payload = {
            "experiment_name": "test",
            "experiment_uri": "/home/user/project",
            "model_uri": "/nfs/mistral",
            "model_id": "mistral-7b",  # Different from parent's llama-7b
            "codebase": {"train.py": "code"},
        }
        resp = client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 409
        assert "model_id" in resp.json()["detail"].lower() or "model" in resp.json()["detail"].lower()

    @patch("graph_lineage.server.app.create_edge")
    @patch("graph_lineage.server.app.create_experiment_node")
    @patch("graph_lineage.server.app.find_parent_experiment")
    def test_pre_resume_explicit(self, mock_find_parent, mock_create, mock_edge, client):
        """Explicit checkpoint_resume_from → strategy=RESUME."""
        parent = Experiment(
            id="parent-001",
            uri="/home/user/project",
            strategy="NEW",
            base=True,
            model_uri="/nfs/llama",
            model_id="llama-7b",
            codebase={"train.py": "code"},
        )
        mock_find_parent.return_value = parent
        mock_create.return_value = "resume-id"

        payload = {
            "experiment_name": "test",
            "experiment_uri": "/home/user/project",
            "model_uri": "/nfs/llama",
            "model_id": "llama-7b",
            "checkpoint_resume_from": "checkpoint-500/model",
            "codebase": {"train.py": "code"},
        }
        resp = client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 200
        assert resp.json()["strategy"] == "RESUME"

    def test_pre_empty_name_validation(self, client):
        """Missing experiment_name → 422 validation error."""
        payload = {"codebase": {"train.py": "x"}}
        resp = client.post("/api/v1/pre", json=payload)
        assert resp.status_code == 422


# ─── POST-EXECUTION TESTS ─────────────────────────────────────────────────────


class TestPostEndpoint:
    @patch("graph_lineage.server.app.update_experiment_status")
    def test_post_completed(self, mock_update, client):
        """Post COMPLETED status → acknowledged."""
        payload = {
            "experiment_id": "exp-001",
            "status": "COMPLETED",
            "metrics_uri": "/logs/run-001/metrics.json",
        }
        resp = client.post("/api/v1/post", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["acknowledged"] is True
        assert data["status"] == "COMPLETED"
        mock_update.assert_called_once_with(
            exp_id="exp-001", status="COMPLETED", exit_msg=None,
        )

    @patch("graph_lineage.server.app.update_experiment_status")
    def test_post_failed_with_message(self, mock_update, client):
        """Post FAILED status with exit message."""
        payload = {
            "experiment_id": "exp-002",
            "status": "FAILED",
            "exit_message": "CUDA out of memory",
        }
        resp = client.post("/api/v1/post", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        mock_update.assert_called_once_with(
            exp_id="exp-002", status="FAILED", exit_msg="CUDA out of memory",
        )

    @patch("graph_lineage.server.app.update_experiment_status")
    def test_post_neo4j_error_returns_500(self, mock_update, client):
        """Neo4j failure during POST → 500."""
        mock_update.side_effect = Exception("Neo4j timeout")

        payload = {"experiment_id": "exp-003", "status": "COMPLETED"}
        resp = client.post("/api/v1/post", json=payload)

        assert resp.status_code == 500
        assert "Neo4j timeout" in resp.json()["detail"]

    def test_post_missing_experiment_id(self, client):
        """Missing experiment_id → 422 validation."""
        payload = {"status": "COMPLETED"}
        resp = client.post("/api/v1/post", json=payload)
        assert resp.status_code == 422
