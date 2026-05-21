"""Tests for message loader and description generator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from graph_lineage.config_file.commit_msg.loader import load_messages
from graph_lineage.diff.description import generate_description


class TestLoadMessages:
    """Tests for load_messages function."""

    def test_load_messages_returns_expected_keys(self):
        """Test 1: load_messages returns dict with required keys."""
        messages = load_messages()
        expected_keys = {"file_modified", "no_changes", "non_critical_changes", "retry", "resume", "critical_files"}
        assert expected_keys.issubset(messages.keys())

    def test_load_messages_from_user_path(self, tmp_path: Path):
        """Test 2: load_messages loads from user-provided YML when file exists."""
        user_yml = tmp_path / "custom.yml"
        user_yml.write_text(
            'file_modified: "CUSTOM {filename}"\n'
            'no_changes: "NOTHING"\n'
            'non_critical_changes: "NON CRIT"\n'
            'retry: "CUSTOM RETRY {exp_id}"\n'
            'resume: "CUSTOM RESUME {exp_id} {ckp_id}"\n'
            "critical_files:\n"
            "  - custom.py\n"
        )
        messages = load_messages(user_path=user_yml)
        assert messages["file_modified"] == "CUSTOM {filename}"

    def test_load_messages_fallback_when_user_path_missing(self, tmp_path: Path):
        """Test 3: load_messages falls back to default when user file does not exist."""
        missing_path = tmp_path / "nonexistent.yml"
        messages = load_messages(user_path=missing_path)
        assert "file_modified" in messages
        assert messages["file_modified"] == "{filename} modified"


class TestGenerateDescription:
    """Tests for generate_description function."""

    def test_single_critical_file_changed(self):
        """Test 4: Single critical file produces 'X modified' message."""
        result = generate_description(changed_files=["train.py"], strategy="BRANCH")
        assert result == "train.py modified"

    def test_multiple_critical_files_changed(self):
        """Test 5: Multiple critical files joined with comma."""
        result = generate_description(
            changed_files=["train.py", "config.yaml"], strategy="BRANCH"
        )
        assert "config.yaml modified" in result
        assert "train.py modified" in result

    def test_no_changes(self):
        """Test 6: Empty changed_files returns no_changes message."""
        result = generate_description(changed_files=[], strategy="BRANCH")
        assert result == "no codebase changes"

    def test_non_critical_changes(self):
        """Test 7: Only non-critical files returns non_critical_changes message."""
        result = generate_description(changed_files=["other.py"], strategy="BRANCH")
        assert result == "codebase changes, but not in critical files"

    def test_retry_strategy(self):
        """Test 8: RETRY strategy returns retry template."""
        result = generate_description(
            changed_files=[], strategy="RETRY", exp_id="e-001"
        )
        assert result == "RETRY FROM e-001"

    def test_resume_strategy(self):
        """Test 9: RESUME strategy returns resume template."""
        result = generate_description(
            changed_files=[], strategy="RESUME", exp_id="e-001", ckp_id="c-001"
        )
        assert result == "RESUME FROM e-001, checkpoint c-001"
