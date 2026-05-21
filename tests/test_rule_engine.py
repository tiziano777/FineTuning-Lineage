"""Tests for graph_lineage.lineage.rule_engine — all 5 strategies."""

from __future__ import annotations

import pytest

from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.config_file.data_classes.model_merging_config import ModelMergingConfig
from graph_lineage.config_file.data_classes.output_config import OutputConfig
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.lineage.rule_engine import RunTypeResult, detect_run_type


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    *,
    merging_enabled: bool = False,
    checkpoint_resume_from: str | None = None,
) -> LineageConfig:
    """Build a minimal valid LineageConfig for testing."""
    return LineageConfig(
        experiment=ExperimentConfig(
            name="test-exp",
            uri="/tmp/test-project",
            checkpoint_resume_from=checkpoint_resume_from,
        ),
        model={"model_name": "llama-7b", "framework": "pytorch"},
        output=OutputConfig(output_dir="/tmp/output"),
        model_merging=ModelMergingConfig(
            enabled=merging_enabled,
            merge_method="linear" if merging_enabled else None,
            sources=["a", "b"] if merging_enabled else [],
        ),
    )


def _make_snapshot(files: dict[str, str] | None = None) -> CodebaseSnapshot:
    """Build a CodebaseSnapshot with given files or defaults."""
    default_files = {
        "config.yaml": "model: llama",
        "prepare.py": "print('prep')",
        "train.py": "print('train')",
        "requirements.txt": "torch==2.0",
    }
    return CodebaseSnapshot(files=files or default_files)


def _make_parent_experiment(snapshot: CodebaseSnapshot) -> Experiment:
    """Build a parent Experiment with hashes matching the given snapshot."""
    hashes = snapshot.hashes()
    return Experiment(
        id="parent-exp-001",
        uri="/tmp/test-project",
        strategy="NEW",
        base=True,
        codebase=snapshot.files,
        config_hash=hashes["config.yaml"],
        prepare_hash=hashes["prepare.py"],
        train_hash=hashes["train.py"],
        requirements_hash=hashes["requirements.txt"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectRunType:
    """Tests for detect_run_type covering all 5 strategies."""

    def test_merge_strategy(self):
        """MERGE when model_merging.enabled is True."""
        config = _make_config(merging_enabled=True)
        snapshot = _make_snapshot()
        parent = _make_parent_experiment(snapshot)

        result = detect_run_type(config, snapshot, parent)

        assert result.strategy == "MERGE"
        assert result.parent_exp_id == "parent-exp-001"

    def test_merge_takes_precedence_over_resume(self):
        """MERGE wins even if checkpoint_resume_from is set."""
        config = _make_config(
            merging_enabled=True,
            checkpoint_resume_from="checkpoint-abc",
        )
        snapshot = _make_snapshot()
        result = detect_run_type(config, snapshot, None)

        assert result.strategy == "MERGE"

    def test_resume_strategy(self):
        """RESUME when checkpoint_resume_from looks like a checkpoint ID."""
        config = _make_config(checkpoint_resume_from="checkpoint-epoch-5")
        snapshot = _make_snapshot()
        parent = _make_parent_experiment(snapshot)

        result = detect_run_type(config, snapshot, parent)

        assert result.strategy == "RESUME"
        assert result.parent_ckp_id == "checkpoint-epoch-5"
        assert result.parent_exp_id == "parent-exp-001"

    def test_resume_with_ckpt_prefix(self):
        """RESUME also matches 'ckpt' prefix."""
        config = _make_config(checkpoint_resume_from="/path/to/ckpt-100")
        snapshot = _make_snapshot()

        result = detect_run_type(config, snapshot, None)

        assert result.strategy == "RESUME"
        assert result.parent_ckp_id == "/path/to/ckpt-100"

    def test_new_strategy(self):
        """NEW when no parent experiment exists."""
        config = _make_config()
        snapshot = _make_snapshot()

        result = detect_run_type(config, snapshot, None)

        assert result.strategy == "NEW"
        assert result.parent_exp_id is None
        assert result.diff_patch is None

    def test_retry_strategy(self):
        """RETRY when all hashes match parent."""
        snapshot = _make_snapshot()
        config = _make_config()
        parent = _make_parent_experiment(snapshot)

        result = detect_run_type(config, snapshot, parent)

        assert result.strategy == "RETRY"
        assert result.parent_exp_id == "parent-exp-001"

    def test_branch_strategy(self):
        """BRANCH when hashes differ from parent."""
        original_snapshot = _make_snapshot()
        config = _make_config()
        parent = _make_parent_experiment(original_snapshot)

        # Modified snapshot — train.py changed
        modified_files = dict(original_snapshot.files)
        modified_files["train.py"] = "print('train v2')"
        current_snapshot = _make_snapshot(files=modified_files)

        result = detect_run_type(config, current_snapshot, parent)

        assert result.strategy == "BRANCH"
        assert result.parent_exp_id == "parent-exp-001"
        assert result.diff_patch is not None
        assert "train.py" in result.diff_patch

    def test_branch_diff_patch_content(self):
        """BRANCH diff_patch contains unified diff for changed files only."""
        original_snapshot = _make_snapshot()
        parent = _make_parent_experiment(original_snapshot)

        modified_files = dict(original_snapshot.files)
        modified_files["config.yaml"] = "model: mistral"
        current_snapshot = _make_snapshot(files=modified_files)

        result = detect_run_type(_make_config(), current_snapshot, parent)

        assert result.strategy == "BRANCH"
        assert set(result.diff_patch.keys()) == {"config.yaml"}
        assert "mistral" in result.diff_patch["config.yaml"]


class TestRunTypeResult:
    """Tests for RunTypeResult dataclass."""

    def test_defaults(self):
        result = RunTypeResult(strategy="NEW")
        assert result.parent_exp_id is None
        assert result.parent_ckp_id is None
        assert result.diff_patch is None

    def test_frozen(self):
        result = RunTypeResult(strategy="NEW")
        with pytest.raises(AttributeError):
            result.strategy = "BRANCH"  # type: ignore[misc]
