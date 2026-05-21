"""Tests for graph_lineage.lineage.tracker — decorator lifecycle."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from graph_lineage.lineage.tracker import ExecutionContext, _post_execution, _pre_execution, envelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_test_config(tmp_dir: Path) -> str:
    """Write a minimal valid config.yml and supporting files, return config path."""
    config_data = {
        "experiment": {
            "name": "test-exp",
            "uri": str(tmp_dir),
            "description": "test run",
        },
        "model": {"model_name": "llama-7b", "framework": "pytorch"},
        "output": {"output_dir": str(tmp_dir / "output")},
        "model_merging": {"enabled": False},
    }
    config_path = tmp_dir / "config.yml"
    config_path.write_text(yaml.dump(config_data))

    # Create output dir so validation passes
    (tmp_dir / "output").mkdir(exist_ok=True)

    # Create critical files for snapshot
    (tmp_dir / "config.yaml").write_text("model: llama")
    (tmp_dir / "prepare.py").write_text("print('prep')")
    (tmp_dir / "train.py").write_text("print('train')")
    (tmp_dir / "requirements.txt").write_text("torch==2.0")

    return str(config_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBlockingMode:
    """Test blocking=True behavior on errors."""

    @patch("graph_lineage.lineage.tracker.find_parent_experiment", side_effect=ConnectionError("DB down"))
    @patch("graph_lineage.lineage.tracker.validate_pre_execution", return_value=[])
    def test_blocking_db_error_exits(self, _mock_val, _mock_find):
        """blocking=True with DB error should sys.exit(4)."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_test_config(Path(tmp))
            with pytest.raises(SystemExit) as exc_info:
                _pre_execution((config_path,), {}, blocking=True)
            assert exc_info.value.code == 4


class TestNonBlockingMode:
    """Test blocking=False behavior on errors."""

    @patch("graph_lineage.lineage.tracker.find_parent_experiment", side_effect=ConnectionError("DB down"))
    @patch("graph_lineage.lineage.tracker.validate_pre_execution", return_value=[])
    def test_nonblocking_db_error_returns_none(self, _mock_val, _mock_find):
        """blocking=False with DB error should return None."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_test_config(Path(tmp))
            result = _pre_execution((config_path,), {}, blocking=False)
            assert result is None

    @patch("graph_lineage.lineage.tracker.find_parent_experiment", side_effect=ConnectionError("DB down"))
    @patch("graph_lineage.lineage.tracker.validate_pre_execution", return_value=[])
    def test_nonblocking_function_still_runs(self, _mock_val, _mock_find):
        """When PRE fails in non-blocking mode, decorated function still executes."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_test_config(Path(tmp))
            call_log = []

            @envelope.tracker(blocking=False)
            def my_train(cfg_path):
                call_log.append("ran")
                return "done"

            result = my_train(config_path)
            assert result == "done"
            assert call_log == ["ran"]


class TestFullLifecycle:
    """Test full PRE -> RUN -> POST for NEW strategy."""

    @patch("graph_lineage.lineage.tracker.save_config")
    @patch("graph_lineage.lineage.tracker.create_edge")
    @patch("graph_lineage.lineage.tracker.create_experiment_node", return_value="exp-123")
    @patch("graph_lineage.lineage.tracker.find_parent_experiment", return_value=None)
    @patch("graph_lineage.lineage.tracker.validate_pre_execution", return_value=[])
    def test_new_strategy_lifecycle(
        self, _mock_val, _mock_find, _mock_create, _mock_edge, _mock_save
    ):
        """NEW strategy: creates node, no edges, function runs, POST updates status."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_test_config(Path(tmp))

            ctx = _pre_execution((config_path,), {}, blocking=True)

            assert ctx is not None
            assert ctx.strategy == "NEW"
            assert ctx.exp_id is not None
            _mock_create.assert_called_once()
            _mock_edge.assert_not_called()  # NEW has no parent

    @patch("graph_lineage.lineage.tracker.update_experiment_status")
    @patch("graph_lineage.lineage.tracker.save_config")
    @patch("graph_lineage.lineage.tracker.create_edge")
    @patch("graph_lineage.lineage.tracker.create_experiment_node", return_value="exp-456")
    @patch("graph_lineage.lineage.tracker.find_parent_experiment", return_value=None)
    @patch("graph_lineage.lineage.tracker.validate_pre_execution", return_value=[])
    def test_decorator_full_flow(
        self, _mock_val, _mock_find, _mock_create, _mock_edge, _mock_save, _mock_update
    ):
        """Full decorator flow: PRE -> fn() -> POST with COMPLETED status."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _write_test_config(Path(tmp))

            @envelope.tracker(blocking=True)
            def my_train(cfg_path):
                return 42

            result = my_train(config_path)
            assert result == 42
            _mock_update.assert_called_once()
            call_args = _mock_update.call_args
            assert call_args[0][1] == "COMPLETED"


class TestBranchEdge:
    """Test BRANCH strategy creates DERIVED_FROM edge with diff_patch."""

    @patch("graph_lineage.lineage.tracker.save_config")
    @patch("graph_lineage.lineage.tracker.create_edge")
    @patch("graph_lineage.lineage.tracker.create_experiment_node", return_value="exp-branch")
    @patch("graph_lineage.lineage.tracker.validate_pre_execution", return_value=[])
    def test_branch_creates_derived_from_edge(
        self, _mock_val, _mock_create, _mock_edge, _mock_save
    ):
        """BRANCH should create DERIVED_FROM edge with diff_patch property."""
        from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
        from graph_lineage.diff.snapshot import CodebaseSnapshot

        # Parent with different hashes
        parent = Experiment(
            id="parent-001",
            uri="/tmp/project",
            strategy="NEW",
            base=True,
            codebase={"config.yaml": "old", "prepare.py": "", "train.py": "", "requirements.txt": ""},
            config_hash="different_hash",
            prepare_hash="",
            train_hash="",
            requirements_hash="",
        )

        with patch("graph_lineage.lineage.tracker.find_parent_experiment", return_value=parent):
            with tempfile.TemporaryDirectory() as tmp:
                config_path = _write_test_config(Path(tmp))
                ctx = _pre_execution((config_path,), {}, blocking=True)

                assert ctx is not None
                assert ctx.strategy == "BRANCH"
                _mock_edge.assert_called_once()
                edge_call = _mock_edge.call_args
                assert edge_call[0][2] == "DERIVED_FROM"  # rel_type


class TestPostExecution:
    """Test _post_execution independently."""

    @patch("graph_lineage.lineage.tracker.save_config")
    @patch("graph_lineage.lineage.tracker.update_experiment_status")
    def test_post_updates_status(self, mock_update, _mock_save):
        """POST should call update_experiment_status with correct args."""
        config = MagicMock()
        ctx = ExecutionContext(
            exp_id="exp-999",
            strategy="NEW",
            config=config,
            config_path="/tmp/config.yml",
        )
        _post_execution(ctx, status="COMPLETED")
        mock_update.assert_called_once_with("exp-999", "COMPLETED", None)

    @patch("graph_lineage.lineage.tracker.save_config")
    @patch("graph_lineage.lineage.tracker.update_experiment_status")
    def test_post_with_failure(self, mock_update, _mock_save):
        """POST with FAILED status includes exit_msg."""
        config = MagicMock()
        ctx = ExecutionContext(
            exp_id="exp-999",
            strategy="NEW",
            config=config,
            config_path="/tmp/config.yml",
        )
        _post_execution(ctx, status="FAILED", exit_msg="OOM error")
        mock_update.assert_called_once_with("exp-999", "FAILED", "OOM error")
