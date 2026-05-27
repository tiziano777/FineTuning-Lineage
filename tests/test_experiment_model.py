"""Tests for Experiment model: imports, field structure, model_uri/model_id."""

import pytest
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment


class TestExperimentModelFixes:
    """Verify Experiment model structure and fields."""

    def test_typing_import_not_git(self):
        """Test 1: Optional comes from typing, not git."""
        import graph_lineage.data_classes.neo4j.nodes.experiment as mod
        import inspect
        source = inspect.getsource(mod)
        assert "from typing import Optional" in source
        assert "from git import Optional" not in source

    def test_codebase_defaults_to_empty_dict(self):
        """Test 2: codebase defaults to empty dict, not string."""
        exp = Experiment(uri="test/path", strategy="NEW")
        assert exp.codebase == {}
        assert isinstance(exp.codebase, dict)

    def test_has_base_field_bool_default_true(self):
        """Test 3: Experiment has base:bool defaulting to True."""
        exp = Experiment(uri="test/path", strategy="NEW")
        assert exp.base is True
        assert isinstance(exp.base, bool)

    def test_has_model_fields(self):
        """Test 4: Experiment has model_uri and model_id fields."""
        exp = Experiment(uri="test/path", strategy="NEW")
        assert exp.model_uri == ""
        assert exp.model_id == ""

    def test_has_changed_files_field(self):
        """Test 5: Experiment has changed_files list field."""
        exp = Experiment(uri="test/path", strategy="BRANCH")
        assert exp.changed_files == []
        assert isinstance(exp.changed_files, list)

    def test_no_old_hash_fields(self):
        """Test 6: Old *_hash fields do NOT exist anymore."""
        fields = set(Experiment.model_fields.keys())
        assert "config_hash" not in fields
        assert "prepare_hash" not in fields
        assert "train_hash" not in fields
        assert "requirements_hash" not in fields

    def test_full_instantiation(self):
        """Test 7: Full instantiation with all new fields."""
        exp = Experiment(
            uri="test/path",
            strategy="BRANCH",
            base=False,
            model_uri="/nfs/models/llama-7b",
            model_id="llama-7b",
            codebase={"train.py": "print('hello')"},
            changed_files=["train.py"],
        )
        assert exp.base is False
        assert exp.model_uri == "/nfs/models/llama-7b"
        assert exp.model_id == "llama-7b"
        assert exp.codebase == {"train.py": "print('hello')"}
        assert exp.changed_files == ["train.py"]
