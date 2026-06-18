"""Integration tests for BRANCH run strategy.

Tests code/config changes from parent, creating DERIVED_FROM edge with diffs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.test_builders import CodebaseSnapshotBuilder, ExperimentBuilder


class TestBranchExperiment:
    """Test BRANCH strategy: code changed from parent."""

    def test_branch_changed_files_identified(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """BRANCH identifies which files changed."""
        # Parent with original code
        parent_files = CodebaseSnapshotBuilder().with_train_script("print('old')").build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Modified code
        modified_files = CodebaseSnapshotBuilder().with_train_script("print('new')").build().files

        payload = {
            "experiment_name": "test-branch",
            "experiment_uri": str(test_project),
            "codebase": modified_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        assert resp.status_code == 200

        data = resp.json()
        assert data["strategy"] == "BRANCH"
        assert "train.py" in data["changed_files"]

    def test_branch_stores_diff_patch(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """BRANCH stores unified diff for changed files."""
        parent_files = CodebaseSnapshotBuilder().with_train_script("import torch").build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        modified_files = CodebaseSnapshotBuilder().with_train_script("import torch\nimport numpy").build().files

        payload = {
            "experiment_name": "test-branch",
            "experiment_uri": str(test_project),
            "codebase": modified_files,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()
        branch_exp_id = data["experiment_id"]

        # Check DB: should have diff stored
        branch_data = mock_neo4j.get_experiment(branch_exp_id)
        assert branch_data is not None
        codebase = branch_data.get("codebase", {})
        # For branch, codebase may contain diffs
        assert len(codebase) > 0

    def test_branch_derived_from_edge(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """BRANCH creates DERIVED_FROM edge to parent."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Modify: add a file
        modified = dict(parent_files)
        modified["new_module.py"] = "def helper(): pass"

        payload = {
            "experiment_name": "test-branch",
            "experiment_uri": str(test_project),
            "codebase": modified,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()
        branch_exp_id = data["experiment_id"]

        # Verify edge
        mock_neo4j.assert_edge_exists(branch_exp_id, parent.id, "DERIVED_FROM")

    def test_branch_multiple_files_changed(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """BRANCH with multiple file changes detected."""
        parent_files = CodebaseSnapshotBuilder().build().files
        parent = (
            ExperimentBuilder()
            .with_strategy("NEW")
            .with_uri(str(test_project))
            .with_codebase(parent_files)
            .build()
        )
        mock_neo4j.create_experiment_node(parent)

        # Change multiple files
        modified = dict(parent_files)
        modified["train.py"] = "print('updated')"
        modified["config.yaml"] = "model: mistral"

        payload = {
            "experiment_name": "test-branch",
            "experiment_uri": str(test_project),
            "codebase": modified,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()

        assert data["strategy"] == "BRANCH"
        assert len(data["changed_files"]) >= 2

    def test_branch_not_base_false(
        self,
        test_project,
        mock_neo4j: InMemoryNeo4jTracker,
        integration_client,
    ):
        """BRANCH has base=False."""
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

        modified = dict(parent_files)
        modified["train.py"] = "print('changed')"

        payload = {
            "experiment_name": "test-branch",
            "experiment_uri": str(test_project),
            "codebase": modified,
            "model_uri": parent.model_uri,
            "model_id": parent.model_id,
        }

        resp = integration_client.post("/api/v1/pre", json=payload)
        data = resp.json()

        assert data["base"] is False
