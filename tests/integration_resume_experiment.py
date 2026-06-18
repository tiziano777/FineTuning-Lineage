"""Integration tests for RESUME run strategy.

Tests resuming training from a checkpoint.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import CodebaseSnapshotBuilder, ExperimentBuilder, CheckpointBuilder


class TestResumeExperiment:
    """Test RESUME strategy: resume from checkpoint."""

    def test_resume_explicit_checkpoint_config(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RESUME detected via explicit checkpoint_resume_from in config."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        payload = {
            "experiment_name": "test-resume",
            "experiment_uri": str(test_project),
            "codebase": parent_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
            "checkpoint_resume_from": "/output/checkpoint-500",
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        assert resp.status_code == 200

        data = resp.json()
        assert data["strategy"] == "RESUME"

    def test_resume_started_from_edge(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RESUME creates STARTED_FROM edge to parent."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        payload = {
            "experiment_name": "test-resume",
            "experiment_uri": str(test_project),
            "codebase": parent_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
            "checkpoint_resume_from": "/output/checkpoint-500",
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()
        resume_exp_id = data["experiment_id"]

        # Verify edge
        mock_neo4j.assert_edge_exists(resume_exp_id, parent.id, "STARTED_FROM")

    def test_resume_from_intermediate_checkpoint(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RESUME from epoch 3 checkpoint works."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Create intermediate checkpoint
        ckp = CheckpointBuilder().with_epoch(3).with_name("checkpoint-3000").build()
        mock_neo4j.create_checkpoint_node(ckp)

        payload = {
            "experiment_name": "test-resume",
            "experiment_uri": str(test_project),
            "codebase": parent_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
            "checkpoint_resume_from": str(ckp.id),
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "RESUME"

    def test_resume_no_codebase_snapshot_stored(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RESUME doesn't store full codebase snapshot."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        payload = {
            "experiment_name": "test-resume",
            "experiment_uri": str(test_project),
            "codebase": parent_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
            "checkpoint_resume_from": "/output/checkpoint-500",
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()
        resume_exp_id = data["experiment_id"]

        # Check DB: RESUME should store minimal codebase
        resume_data = mock_neo4j.get_experiment(resume_exp_id)
        assert resume_data is not None
        # Minimal or empty codebase for RESUME
        codebase = resume_data.get("codebase", {})
        assert len(codebase) == 0 or "checkpoint" in str(resume_data)

    def test_resume_derived_not_base(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """RESUME experiments have base=False."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_base(True)
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        payload = {
            "experiment_name": "test-resume",
            "experiment_uri": str(test_project),
            "codebase": parent_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
            "checkpoint_resume_from": "/output/checkpoint-500",
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()

        assert data["base"] is False
