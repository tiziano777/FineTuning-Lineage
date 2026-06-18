"""Integration tests for RETRY run strategy.

Tests running with identical code and config, which should create a RETRY_OF edge.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import (
    CodebaseSnapshotBuilder,
    ExperimentBuilder,
    ConfigBuilder,
)
from graph_lineage.diff.snapshot import CodebaseSnapshot


class TestRetryExperiment:
    """Test RETRY strategy: identical code and config."""

    def test_retry_identical_codebase(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RETRY detected when codebase hash is identical to parent."""
        # Create and store parent experiment with exact codebase
        codebase = CodebaseSnapshotBuilder().build()
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_base(True)
            .with_uri(str(test_project))
            .with_codebase(codebase.files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Now run with identical code
        payload = {
            "experiment_name": "test-retry",
            "experiment_uri": str(test_project),
            "codebase": codebase.files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "RETRY"
        assert data["base"] is False

    def test_retry_of_edge_created(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RETRY creates RETRY_OF edge to parent."""
        # Create parent
        codebase = CodebaseSnapshotBuilder().build()
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(codebase.files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Run RETRY
        payload = {
            "experiment_name": "test-retry",
            "experiment_uri": str(test_project),
            "codebase": codebase.files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        assert resp.status_code == 200

        data = resp.json()
        retry_exp_id = data["experiment_id"]

        # Verify RETRY_OF edge exists
        mock_neo4j.assert_edge_exists(retry_exp_id, parent.id, "RETRY_OF")

    def test_retry_empty_changed_files(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RETRY has empty changed_files list."""
        # Create parent
        codebase = CodebaseSnapshotBuilder().build()
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(codebase.files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Run identical
        payload = {
            "experiment_name": "test-retry",
            "experiment_uri": str(test_project),
            "codebase": codebase.files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()

        assert data["strategy"] == "RETRY"
        assert data["changed_files"] == []

    def test_retry_derived_not_base(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RETRY experiments have base=False."""
        # Create parent with base=True
        codebase = CodebaseSnapshotBuilder().build()
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_base(True)
            .with_uri(str(test_project))
            .with_codebase(codebase.files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Run RETRY
        payload = {
            "experiment_name": "test-retry",
            "experiment_uri": str(test_project),
            "codebase": codebase.files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()

        # RETRY child should have base=False
        assert data["base"] is False

    def test_retry_minimal_codebase_stored(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RETRY stores minimal codebase (no full snapshot)."""
        # Create parent
        codebase = CodebaseSnapshotBuilder().build()
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(codebase.files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Run RETRY
        payload = {
            "experiment_name": "test-retry",
            "experiment_uri": str(test_project),
            "codebase": codebase.files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()
        retry_exp_id = data["experiment_id"]

        # Check DB state
        retry_data = mock_neo4j.get_experiment(retry_exp_id)
        assert retry_data is not None
        # RETRY typically stores empty or minimal codebase
        assert retry_data.get("codebase") == {} or len(retry_data.get("codebase", {})) == 0
