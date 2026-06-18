"""Integration tests for error cases and edge cases.

Tests error handling, validation failures, and edge cases.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import ExperimentBuilder, CodebaseSnapshotBuilder


class TestErrorCases:
    """Test error handling and validation."""

    def test_model_id_mismatch_409(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """Model ID mismatch with parent → 409 Conflict."""
        # Create parent with one model
        codebase = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_model_id("llama-7b")
            .with_codebase(codebase)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Try to run with different model_id
        payload = {
            "experiment_name": "test-conflict",
            "experiment_uri": str(test_project),
            "codebase": codebase,
            "model_uri": parent.model_uri,
            "model_id": "mistral-7b",  # Different!
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        # Should fail due to model mismatch
        assert resp.status_code in [409, 400, 422]

    def test_missing_base_experiment_not_found(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """Non-existent base experiment raises error."""
        payload = {
            "experiment_name": "test-not-found",
            "experiment_uri": str(test_project),
            "codebase": {"train.py": "import torch"},
            "base_experiment_id": "nonexistent-id-12345",
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        # Should fail - base experiment not found
        assert resp.status_code in [404, 422, 400]

    def test_post_without_pre_context_fails(
        self,
        integration_client,
    ):
        """POST fails for non-existent experiment."""
        payload = {
            "experiment_id": "nonexistent-exp-id",
            "status": "COMPLETED",
        }

        resp = integration_client.post("/api/v1/post", json=payload)
        # Should handle gracefully - no experiment to update
        assert resp.status_code in [404, 400]

    def test_checkpoint_without_experiment_fails(
        self,
        integration_client,
    ):
        """Checkpoint creation fails if experiment doesn't exist."""
        payload = {
            "experiment_id": "nonexistent-exp",
            "name": "checkpoint-500",
            "epoch": 1,
            "run": 1,
            "uri": "/output/checkpoint-500",
            "metrics": {},
        }

        resp = integration_client.post("/api/v1/checkpoint", json=payload)
        # Should handle gracefully - experiment doesn't exist
        assert resp.status_code in [404, 400]

    def test_empty_codebase_accepted(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """Empty codebase still creates experiment."""
        payload = {
            "experiment_name": "test-empty",
            "experiment_uri": str(test_project),
            "codebase": {},  # Empty
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        # Should still work - empty codebase is valid for NEW
        assert resp.status_code == 200

    def test_duplicate_experiment_ids_prevented(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """Each experiment gets unique ID."""
        # Create first experiment
        payload1 = {
            "experiment_name": "test-1",
            "experiment_uri": str(test_project) + "/run1",
            "codebase": {"train.py": "import torch"},
        }
        resp1 = integration_client.post("/api/v1/pre", json=payload1)
        exp_id_1 = resp1.json()["experiment_id"]

        # Create second experiment
        payload2 = {
            "experiment_name": "test-2",
            "experiment_uri": str(test_project) + "/run2",
            "codebase": {"train.py": "import torch"},
        }
        resp2 = integration_client.post("/api/v1/pre", json=payload2)
        exp_id_2 = resp2.json()["experiment_id"]

        # IDs should be different
        assert exp_id_1 != exp_id_2

    def test_invalid_status_values(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """Invalid status transitions handled."""
        # Create experiment
        payload = {
            "experiment_name": "test-status",
            "experiment_uri": str(test_project),
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Try invalid status
        post_payload = {
            "experiment_id": exp_id,
            "status": "INVALID_STATUS",
        }

        resp = integration_client.post("/api/v1/post", json=post_payload)
        # Should either accept or reject based on validation
        # Acceptable to be lenient and store whatever is sent
        assert resp.status_code in [200, 422]

    def test_checkpoint_negative_epoch_handled(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Negative epoch values handled."""
        # Create experiment
        payload = {
            "experiment_name": "test-ckp",
            "experiment_uri": "/tmp/test-ckp",
            "codebase": {"train.py": "import torch"},
        }
        resp = integration_client.post("/api/v1/pre", json=payload)
        exp_id = resp.json()["experiment_id"]

        # Try negative epoch (should be rejected or handled gracefully)
        ckp_payload = {
            "experiment_id": exp_id,
            "name": "checkpoint-invalid",
            "epoch": -1,
            "run": 1,
            "uri": "/output/checkpoint-invalid",
            "metrics": {},
        }

        resp = integration_client.post("/api/v1/checkpoint", json=ckp_payload)
        # Either rejected or accepted - validation depends on schema
        assert resp.status_code in [200, 422]
