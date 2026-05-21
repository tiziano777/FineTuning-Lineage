"""Tests for graph_lineage.config.schema — Pydantic model parsing."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig


def _minimal_config(**overrides) -> dict:
    """Return minimal valid config dict."""
    base = {
        "experiment": {
            "name": "test_exp",
            "uri": "/tmp/project",
        },
        "model": {
            "model_name": "llama-7b",
            "framework": "pytorch",
        },
        "output": {
            "output_dir": "./outputs",
        },
    }
    base.update(overrides)
    return base


class TestLineageConfigParsing:
    """Valid config parsing."""

    def test_minimal_config(self):
        cfg = LineageConfig.model_validate(_minimal_config())
        assert cfg.experiment.name == "test_exp"
        assert cfg.experiment.uri == "/tmp/project"
        assert cfg.experiment.base is True
        assert cfg.experiment.id is None

    def test_full_experiment_fields(self):
        data = _minimal_config()
        data["experiment"].update({
            "id": "abc-123",
            "previous_experiment_id": "prev-456",
            "base_experiment_id": "base-789",
            "base": False,
            "description": "A test",
            "status": "RUNNING",
            "checkpoint_resume_from": "/path/to/ckp",
        })
        cfg = LineageConfig.model_validate(data)
        assert cfg.experiment.id == "abc-123"
        assert cfg.experiment.base is False
        assert cfg.experiment.previous_experiment_id == "prev-456"
        assert cfg.experiment.base_experiment_id == "base-789"

    def test_flexible_model_dict(self):
        data = _minimal_config()
        data["model"]["learning_rate"] = 0.001
        data["model"]["quantization"] = "4bit"
        cfg = LineageConfig.model_validate(data)
        assert cfg.model["learning_rate"] == 0.001
        assert cfg.model["quantization"] == "4bit"

    def test_flexible_hardware_dict(self):
        data = _minimal_config()
        data["hardware"] = {"gpu_count": 4, "gpu_type": "A100"}
        cfg = LineageConfig.model_validate(data)
        assert cfg.hardware["gpu_count"] == 4

    def test_recipe_with_entries(self):
        data = _minimal_config()
        data["recipe"] = {
            "recipe_id": "r-123",
            "recipe_name": "my_recipe",
            "entries": {
                "/path/ds": {
                    "chat_type": "instruction",
                    "dist_id": "d-001",
                    "dist_name": "test_dist",
                    "dist_uri": "/data/dist",
                    "samples": 1000,
                    "tokens": 50000,
                    "words": 40000,
                },
            },
        }
        cfg = LineageConfig.model_validate(data)
        assert cfg.recipe.recipe_id == "r-123"
        assert "/path/ds" in cfg.recipe.entries

    def test_model_merging_config(self):
        data = _minimal_config()
        data["model_merging"] = {
            "enabled": True,
            "merge_method": "linear",
            "sources": ["ckp-1", "ckp-2"],
        }
        cfg = LineageConfig.model_validate(data)
        assert cfg.model_merging.enabled is True
        assert len(cfg.model_merging.sources) == 2


class TestLineageConfigValidationErrors:
    """Invalid config parsing — should raise."""

    def test_missing_experiment_name(self):
        data = _minimal_config()
        data["experiment"]["name"] = ""
        with pytest.raises(PydanticValidationError):
            LineageConfig.model_validate(data)

    def test_missing_experiment_uri(self):
        data = _minimal_config()
        data["experiment"]["uri"] = ""
        with pytest.raises(PydanticValidationError):
            LineageConfig.model_validate(data)

    def test_missing_model_name(self):
        data = _minimal_config()
        data["model"]["model_name"] = ""
        with pytest.raises(PydanticValidationError):
            LineageConfig.model_validate(data)

    def test_missing_framework(self):
        data = _minimal_config()
        data["model"]["framework"] = ""
        with pytest.raises(PydanticValidationError):
            LineageConfig.model_validate(data)

    def test_missing_model_key_entirely(self):
        data = _minimal_config()
        del data["model"]["model_name"]
        with pytest.raises(PydanticValidationError):
            LineageConfig.model_validate(data)

    def test_missing_output_dir(self):
        data = _minimal_config()
        data["output"]["output_dir"] = ""
        with pytest.raises(PydanticValidationError):
            LineageConfig.model_validate(data)
