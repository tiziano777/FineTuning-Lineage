"""Integration tests for checkpoint callback tracking.

Tests tracking checkpoint creation and metrics during training.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import CheckpointBuilder


class TestCheckpointCallbacks:
    """Test checkpoint tracking during training."""

    def test_checkpoint_created_tracked(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Checkpoint creation tracked via API."""
        # Create experiment first
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Create checkpoint
        ckp_payload = {
            "experiment_id": exp_id,
            "name": "checkpoint-500",
            "epoch": 1,
            "run": 1,
            "uri": "/output/checkpoint-500",
            "metrics": {"loss": 0.5},
        }

        resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoint_id" in data

    def test_checkpoint_linked_to_experiment(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Checkpoint has PRODUCED edge from experiment."""
        # Create experiment
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Create checkpoint
        ckp_payload = {
            "experiment_id": exp_id,
            "name": "checkpoint-500",
            "epoch": 1,
            "run": 1,
            "uri": "/output/checkpoint-500",
            "metrics": {"loss": 0.5},
        }

        resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
        ckp_id = resp.json()["checkpoint_id"]

        # Verify edge exists
        mock_neo4j.assert_edge_exists(exp_id, ckp_id, "PRODUCED")

    def test_multiple_checkpoints_sequence(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Multiple epochs of checkpoints tracked."""
        # Create experiment
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Create 3 checkpoints
        ckp_ids = []
        for epoch in range(1, 4):
            ckp_payload = {
                "experiment_id": exp_id,
                "name": f"checkpoint-{epoch * 500}",
                "epoch": epoch,
                "run": 1,
                "uri": f"/output/checkpoint-{epoch * 500}",
                "metrics": {"loss": 1.0 / epoch},
            }
            resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
            ckp_ids.append(resp.json()["checkpoint_id"])

        # Verify all checkpoints created and linked
        assert len(ckp_ids) == 3
        mock_neo4j.assert_checkpoint_count(3)

        # Verify all have PRODUCED edges from experiment
        edges = mock_neo4j.get_edges_of_type("PRODUCED")
        assert len(edges) == 3

    def test_checkpoint_metrics_stored(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Checkpoint metrics captured and stored."""
        # Create experiment
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Create checkpoint with specific metrics
        metrics = {"loss": 0.123, "accuracy": 0.98, "val_loss": 0.456}
        ckp_payload = {
            "experiment_id": exp_id,
            "name": "checkpoint-500",
            "epoch": 1,
            "run": 1,
            "uri": "/output/checkpoint-500",
            "metrics": metrics,
        }

        resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
        ckp_id = resp.json()["checkpoint_id"]

        # Verify metrics stored
        ckp_data = mock_neo4j.get_checkpoint(ckp_id)
        assert ckp_data is not None
        assert ckp_data.get("metrics") == metrics

    def test_checkpoint_uri_stored(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Checkpoint file URI stored correctly."""
        # Create experiment
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Create checkpoint with specific URI
        uri = "/mnt/checkpoints/experiment-abc/checkpoint-1000"
        ckp_payload = {
            "experiment_id": exp_id,
            "name": "checkpoint-1000",
            "epoch": 2,
            "run": 1,
            "uri": uri,
            "metrics": {},
        }

        resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
        ckp_id = resp.json()["checkpoint_id"]

        # Verify URI stored
        ckp_data = mock_neo4j.get_checkpoint(ckp_id)
        assert ckp_data is not None
        assert ckp_data.get("uri") == uri

    def test_checkpoint_epoch_info_stored(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Checkpoint epoch and run counters stored."""
        # Create experiment
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Create checkpoint at epoch 3
        ckp_payload = {
            "experiment_id": exp_id,
            "name": "checkpoint-1500",
            "epoch": 3,
            "run": 2,
            "uri": "/output/checkpoint-1500",
            "metrics": {"loss": 0.25},
        }

        resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
        ckp_id = resp.json()["checkpoint_id"]

        # Verify epoch and run stored
        ckp_data = mock_neo4j.get_checkpoint(ckp_id)
        assert ckp_data is not None
        assert ckp_data.get("epoch") == 3
        assert ckp_data.get("run") == 2
