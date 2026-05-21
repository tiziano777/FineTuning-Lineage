"""Tests for graph_lineage.config.writer — load/save round-trip."""

import pytest
import yaml

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.config_file.writer import load_config, save_config
from graph_lineage.storage.local_provider import LocalStorageProvider


@pytest.fixture
def storage(tmp_path):
    return LocalStorageProvider(str(tmp_path))


@pytest.fixture
def config_path():
    return "config.yml"


@pytest.fixture
def sample_yaml():
    return {
        "experiment": {
            "name": "test_exp",
            "uri": "/tmp/project",
        },
        "model": {
            "model_name": "llama-7b",
            "framework": "pytorch",
            "lr": 0.001,
        },
        "output": {
            "output_dir": "./outputs",
        },
    }


class TestLoadConfig:
    def test_load_valid_config(self, storage, config_path, sample_yaml, tmp_path):
        (tmp_path / config_path).write_text(yaml.dump(sample_yaml))
        cfg = load_config(config_path, storage)
        assert cfg.experiment.name == "test_exp"
        assert cfg.model["lr"] == 0.001

    def test_load_missing_file(self, storage, config_path):
        with pytest.raises(FileNotFoundError):
            load_config(config_path, storage)

    def test_load_invalid_yaml(self, storage, config_path, tmp_path):
        (tmp_path / config_path).write_text("not: [valid: yaml: {{")
        with pytest.raises(Exception):
            load_config(config_path, storage)


class TestSaveConfig:
    def test_save_creates_file(self, storage, config_path, sample_yaml, tmp_path):
        cfg = LineageConfig.model_validate(sample_yaml)
        save_config(cfg, str(tmp_path / config_path), storage)
        assert (tmp_path / config_path).exists()

    def test_save_creates_backup(self, storage, config_path, sample_yaml, tmp_path):
        # Write initial
        path = str(tmp_path / config_path)
        (tmp_path / config_path).write_text("old content")
        cfg = LineageConfig.model_validate(sample_yaml)
        save_config(cfg, path, storage)
        # Backup should exist
        backups = list(tmp_path.glob("*.bak.*"))
        assert len(backups) == 1


class TestRoundTrip:
    def test_round_trip_preserves_data(self, storage, config_path, sample_yaml, tmp_path):
        path = str(tmp_path / config_path)
        # Write initial YAML
        (tmp_path / config_path).write_text(yaml.dump(sample_yaml))
        # Load
        cfg = load_config(config_path, storage)
        # Modify
        cfg.experiment.id = "generated-uuid-123"
        cfg.experiment.base = True
        # Save
        save_config(cfg, path, storage)
        # Reload
        cfg2 = load_config(config_path, storage)
        assert cfg2.experiment.id == "generated-uuid-123"
        assert cfg2.experiment.name == "test_exp"
        assert cfg2.model["lr"] == 0.001

    def test_zone_comments_present(self, storage, config_path, sample_yaml, tmp_path):
        path = str(tmp_path / config_path)
        cfg = LineageConfig.model_validate(sample_yaml)
        save_config(cfg, path, storage)
        content = (tmp_path / config_path).read_text()
        assert "LINEAGE-MANAGED" in content
        assert "USER-DEFINED" in content
