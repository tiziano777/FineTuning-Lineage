"""Tests for Experiment model fixes: imports, field renames, base field."""

import pytest
from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment


class TestExperimentModelFixes:
    """Verify Experiment model bug fixes and field renames."""

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

    def test_has_hash_fields(self):
        """Test 4: Experiment has *_hash fields (str, default '')."""
        exp = Experiment(uri="test/path", strategy="NEW")
        assert exp.config_hash == ""
        assert exp.prepare_hash == ""
        assert exp.train_hash == ""
        assert exp.requirements_hash == ""

    def test_no_old_bare_fields(self):
        """Test 5: Old fields config, prepare, train, requirements do NOT exist."""
        exp = Experiment(uri="test/path", strategy="NEW")
        fields = set(exp.model_fields.keys())
        # Only *_hash variants should exist, not bare names
        assert "config" not in fields
        assert "prepare" not in fields
        assert "train" not in fields
        assert "requirements" not in fields

    def test_full_instantiation(self):
        """Test 6: Full instantiation with all new fields."""
        exp = Experiment(
            uri="test/path",
            strategy="BRANCH",
            base=False,
            config_hash="abc123",
            prepare_hash="def456",
            train_hash="ghi789",
            requirements_hash="jkl012",
            codebase={"train.py": "print('hello')"},
        )
        assert exp.base is False
        assert exp.config_hash == "abc123"
        assert exp.prepare_hash == "def456"
        assert exp.train_hash == "ghi789"
        assert exp.requirements_hash == "jkl012"
        assert exp.codebase == {"train.py": "print('hello')"}
