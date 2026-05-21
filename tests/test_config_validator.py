"""Tests for graph_lineage.config.validator — pre-execution checks."""

import pytest

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.config_file.validator import validate_pre_execution
from graph_lineage.storage.local_provider import LocalStorageProvider


def _make_config(**overrides) -> LineageConfig:
    """Create a valid LineageConfig, overriding specific fields."""
    data = {
        "experiment": {
            "name": "test_exp",
            "uri": "/tmp",
        },
        "model": {
            "model_name": "llama-7b",
            "framework": "pytorch",
        },
        "output": {
            "output_dir": "/tmp",
        },
    }
    for key, val in overrides.items():
        parts = key.split(".")
        target = data
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = val
    return LineageConfig.model_validate(data)


@pytest.fixture
def storage(tmp_path):
    """LocalStorageProvider rooted at tmp_path."""
    return LocalStorageProvider(str(tmp_path))


class TestValidatorChecks:
    """Each of the 10 validation checks."""

    def test_check1_uri_not_exists(self, storage):
        cfg = _make_config(**{"experiment.uri": "/nonexistent/path"})
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "experiment.uri" and e.exit_code == 2 for e in errors)

    def test_check2_output_not_writable(self, storage, tmp_path):
        # Create a read-only dir
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        ro_dir.chmod(0o444)
        cfg = _make_config(**{"experiment.uri": str(tmp_path), "output.output_dir": str(ro_dir / "sub")})
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "output.output_dir" and e.exit_code == 3 for e in errors)
        ro_dir.chmod(0o755)  # cleanup

    def test_check3_model_name_empty(self, storage, tmp_path):
        cfg = _make_config(**{"experiment.uri": str(tmp_path)})
        # Override model dict post-creation
        cfg.model["model_name"] = ""
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "model.model_name" and e.exit_code == 2 for e in errors)

    def test_check4_framework_empty(self, storage, tmp_path):
        cfg = _make_config(**{"experiment.uri": str(tmp_path)})
        cfg.model["framework"] = ""
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "model.framework" and e.exit_code == 2 for e in errors)

    def test_check5_experiment_name_empty(self, storage, tmp_path):
        # Can't create with empty name (Pydantic blocks), so test validator separately
        # by patching the object
        cfg = _make_config(**{"experiment.uri": str(tmp_path)})
        object.__setattr__(cfg.experiment, "name", "")
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "experiment.name" and e.exit_code == 2 for e in errors)

    def test_check6_checkpoint_resume_not_resolvable(self, storage, tmp_path):
        cfg = _make_config(**{
            "experiment.uri": str(tmp_path),
            "experiment.checkpoint_resume_from": "/nonexistent/ckp",
        })
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "experiment.checkpoint_resume_from" and e.exit_code == 3 for e in errors)

    def test_check7_merge_sources_insufficient(self, storage, tmp_path):
        cfg = _make_config(**{"experiment.uri": str(tmp_path)})
        cfg.model_merging.enabled = True
        cfg.model_merging.merge_method = "linear"
        cfg.model_merging.sources = ["only_one"]
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "model_merging.sources" and e.exit_code == 2 for e in errors)

    def test_check8_merge_method_invalid(self, storage, tmp_path):
        cfg = _make_config(**{"experiment.uri": str(tmp_path)})
        cfg.model_merging.enabled = True
        cfg.model_merging.merge_method = "invalid_method"
        cfg.model_merging.sources = ["a", "b"]
        errors = validate_pre_execution(cfg, storage)
        assert any(e.field == "model_merging.merge_method" and e.exit_code == 2 for e in errors)

    def test_check9_conflict_resume_and_merge(self, storage, tmp_path):
        # Create a file to act as checkpoint
        ckp = tmp_path / "ckp"
        ckp.touch()
        cfg = _make_config(**{
            "experiment.uri": str(tmp_path),
            "experiment.checkpoint_resume_from": str(ckp),
        })
        cfg.model_merging.enabled = True
        cfg.model_merging.merge_method = "linear"
        cfg.model_merging.sources = ["a", "b"]
        errors = validate_pre_execution(cfg, storage)
        assert any(e.exit_code == 5 for e in errors)

    def test_check10_recipe_guard_mismatch(self, storage, tmp_path):
        cfg = _make_config(**{"experiment.uri": str(tmp_path)})
        # Build proper RecipeEntry objects for current config
        from graph_lineage.config_file.data_classes.recipe_config import RecipeEntry
        cfg.recipe.entries = {
            "/path/a": RecipeEntry(
                chat_type="instruction", dist_id="d1", dist_name="ds",
                dist_uri="/data/a", samples=100, tokens=5000, words=4000,
            ),
        }
        # Previous snapshot (serialized form) with different samples
        previous = {
            "/path/a": RecipeEntry(
                chat_type="instruction", dist_id="d1", dist_name="ds",
                dist_uri="/data/a", samples=200, tokens=5000, words=4000,
            ),
        }
        errors = validate_pre_execution(cfg, storage, previous_recipe_snapshot=previous)
        assert any(e.field == "recipe.entries" and e.exit_code == 5 for e in errors)

    def test_valid_config_no_errors(self, storage, tmp_path):
        cfg = _make_config(**{"experiment.uri": str(tmp_path), "output.output_dir": str(tmp_path)})
        errors = validate_pre_execution(cfg, storage)
        assert errors == []
