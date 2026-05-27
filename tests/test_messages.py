"""Tests for auto-generated experiment descriptions."""

from __future__ import annotations

from graph_lineage.diff.description import generate_description


class TestGenerateDescription:
    """Tests for generate_description function."""

    def test_new_strategy(self):
        """NEW strategy returns base experiment description."""
        result = generate_description(strategy="NEW")
        assert result == "Initial experiment (base)"

    def test_branch_with_changed_files(self):
        """BRANCH with changed files lists them."""
        result = generate_description(
            strategy="BRANCH", changed_files=["train.py", "config.yml"]
        )
        assert "files changed:" in result
        assert "train.py" in result
        assert "config.yml" in result

    def test_branch_no_changed_files(self):
        """BRANCH without file list returns generic message."""
        result = generate_description(strategy="BRANCH", changed_files=[])
        assert "Branch" in result

    def test_retry_strategy(self):
        """RETRY strategy references parent experiment."""
        result = generate_description(strategy="RETRY", exp_id="e-001")
        assert "Retry" in result
        assert "e-001" in result

    def test_retry_no_exp_id(self):
        """RETRY without exp_id gives generic message."""
        result = generate_description(strategy="RETRY")
        assert "Retry" in result

    def test_resume_strategy(self):
        """RESUME strategy references checkpoint and parent."""
        result = generate_description(
            strategy="RESUME", exp_id="e-001", ckp_id="/nfs/checkpoints/ckp-500"
        )
        assert "Resume" in result
        assert "/nfs/checkpoints/ckp-500" in result
        assert "e-001" in result

    def test_merge_strategy(self):
        """MERGE strategy returns merge description."""
        result = generate_description(strategy="MERGE", exp_id="e-002")
        assert "merge" in result.lower()
        assert "e-002" in result

    def test_unknown_strategy(self):
        """Unknown strategy returns informative message."""
        result = generate_description(strategy="UNKNOWN")
        assert "Unknown" in result
