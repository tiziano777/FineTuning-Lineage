"""Integration tests for NEW run strategy.

Tests the simplest case: first execution with no parent experiment in the database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from modules.lineage.client import LineageClient
from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import CodebaseSnapshotBuilder, PreRequestBuilder


class TestNewExperiment:
    """Test NEW strategy: first run with no parent in database."""

    def test_new_detected_no_parent(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """First run detects NEW strategy when no parent exists."""
        ctx = lineage_client.pre_execution()

        assert ctx.strategy == "NEW"
        assert ctx.experiment_id is not None
        mock_neo4j.assert_experiment_created(ctx.experiment_id, "NEW", "RUNNING")

    def test_new_stores_full_codebase(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """NEW experiment stores full codebase snapshot."""
        ctx = lineage_client.pre_execution()

        exp_data = mock_neo4j.get_experiment(ctx.experiment_id)
        assert exp_data is not None

        # Should have codebase field with files
        codebase = exp_data.get("codebase", {})
        assert "train.py" in codebase
        assert "config.yaml" in codebase or "config.yml" in codebase

    def test_new_base_true(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """NEW experiments have base=True."""
        ctx = lineage_client.pre_execution()

        exp_data = mock_neo4j.get_experiment(ctx.experiment_id)
        assert exp_data is not None
        assert exp_data.get("base") is True

    def test_new_no_edges_created(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """NEW strategy creates no lineage edges."""
        ctx = lineage_client.pre_execution()

        # Check edges from the new experiment
        edges_from_exp = mock_neo4j.get_edges_from(ctx.experiment_id)

        # Should have no edges for NEW (no parent to link to)
        assert len(edges_from_exp) == 0

    def test_new_post_updates_status(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """POST updates NEW experiment status to COMPLETED."""
        ctx = lineage_client.pre_execution()
        assert ctx.experiment_id is not None

        # Simulate training completion
        lineage_client.post_execution(ctx, status="COMPLETED")

        exp_data = mock_neo4j.get_experiment(ctx.experiment_id)
        assert exp_data is not None
        assert exp_data.get("status") == "COMPLETED"

    def test_new_post_with_failed_status(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """POST with FAILED status stores exit message."""
        ctx = lineage_client.pre_execution()
        assert ctx.experiment_id is not None

        # Simulate training failure
        error_msg = "CUDA out of memory"
        lineage_client.post_execution(ctx, status="FAILED", exit_message=error_msg)

        exp_data = mock_neo4j.get_experiment(ctx.experiment_id)
        assert exp_data is not None
        assert exp_data.get("status") == "FAILED"
        assert exp_data.get("exit_message") == error_msg

    def test_new_response_contains_required_fields(
        self,
        integration_client,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """PreResponse for NEW contains all required fields."""
        payload = (
            PreRequestBuilder()
            .with_experiment_name("test-new")
            .with_experiment_uri("/tmp/test-new")
            .build()
        )

        resp = integration_client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["experiment_id"]
        assert data["strategy"] == "NEW"
        assert data["base"] is True
        assert "description" in data
        assert "changed_files" in data
        assert data["changed_files"] == []  # No changes for NEW

    def test_multiple_new_experiments_separate(
        self,
        lineage_client: LineageClient,
        mock_neo4j: InMemoryNeo4jTracker,
    ):
        """Multiple NEW experiments don't interfere if different URIs."""
        # First NEW experiment
        ctx1 = lineage_client.pre_execution()
        exp_id_1 = ctx1.experiment_id

        # Both should be in DB with different IDs
        assert ctx1.strategy == "NEW"
        mock_neo4j.assert_experiment_count(1)

        # Verify first is there
        exp_data_1 = mock_neo4j.get_experiment(exp_id_1)
        assert exp_data_1 is not None
        assert exp_data_1.get("strategy") == "NEW"
