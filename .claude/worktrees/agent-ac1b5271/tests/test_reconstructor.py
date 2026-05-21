"""Tests for codebase reconstructor from lineage chain."""

from __future__ import annotations

import pytest

from graph_lineage.diff.reconstructor import (
    MAX_CHAIN_DEPTH,
    apply_unified_diff,
    reconstruct_codebase,
)
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.diff.differ import compute_snapshot_diff


class TestApplyUnifiedDiff:
    """Tests for apply_unified_diff function."""

    def test_apply_simple_patch(self):
        """Test 1: Correctly applies a simple add/remove patch."""
        original = "line1\nline2\nline3\n"
        # Unified diff that removes line2 and adds line2_new
        patch = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_new\n"
            " line3\n"
        )
        result = apply_unified_diff(original, patch)
        assert result == "line1\nline2_new\nline3\n"

    def test_apply_empty_patch_returns_original(self):
        """Test 2: Empty patch returns original unchanged."""
        original = "hello\nworld\n"
        result = apply_unified_diff(original, "")
        assert result == original


class TestReconstructCodebase:
    """Tests for reconstruct_codebase function."""

    def test_single_base_returns_snapshot(self):
        """Test 3: Single base experiment returns full snapshot content."""
        chain = [{"codebase": {"train.py": "print('hello')\n", "config.yaml": "lr: 0.01\n"}}]
        result = reconstruct_codebase(chain)
        assert result == {"train.py": "print('hello')\n", "config.yaml": "lr: 0.01\n"}

    def test_base_plus_one_derived(self):
        """Test 4: Base + 1 derived correctly applies diff."""
        base = {"train.py": "line1\nline2\n"}
        diff_patch = (
            "--- a/train.py\n"
            "+++ b/train.py\n"
            "@@ -1,2 +1,2 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
        )
        chain = [{"codebase": base}, {"codebase": {"train.py": diff_patch}}]
        result = reconstruct_codebase(chain)
        assert result == {"train.py": "line1\nline2_modified\n"}

    def test_base_plus_two_derived(self):
        """Test 5: Base + 2 derived applies diffs in order."""
        base = {"train.py": "a\nb\nc\n"}
        diff1 = (
            "--- a/train.py\n"
            "+++ b/train.py\n"
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            "-b\n"
            "+B\n"
            " c\n"
        )
        diff2 = (
            "--- a/train.py\n"
            "+++ b/train.py\n"
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            " B\n"
            "-c\n"
            "+C\n"
        )
        chain = [
            {"codebase": base},
            {"codebase": {"train.py": diff1}},
            {"codebase": {"train.py": diff2}},
        ]
        result = reconstruct_codebase(chain)
        assert result == {"train.py": "a\nB\nC\n"}

    def test_round_trip(self):
        """Test 6: snapshot A -> diff -> reconstruct from [A, diff] == B."""
        snap_a = CodebaseSnapshot(files={"train.py": "x = 1\ny = 2\n", "config.yaml": "lr: 0.01\n"})
        snap_b = CodebaseSnapshot(files={"train.py": "x = 1\ny = 3\n", "config.yaml": "lr: 0.01\n"})

        diffs = compute_snapshot_diff(snap_a, snap_b)

        chain = [{"codebase": snap_a.files}, {"codebase": diffs}]
        result = reconstruct_codebase(chain)
        assert result == snap_b.files

    def test_max_depth_guard(self):
        """Test 7: Chain > MAX_CHAIN_DEPTH raises ValueError."""
        chain = [{"codebase": {"f.py": "x\n"}}] + [{"codebase": {}}] * MAX_CHAIN_DEPTH
        assert len(chain) == MAX_CHAIN_DEPTH + 1
        with pytest.raises(ValueError, match="depth"):
            reconstruct_codebase(chain)

    def test_new_file_in_diff(self):
        """Test 8: New file in diff (not in base) handled correctly."""
        base = {"train.py": "hello\n"}
        # A diff that adds a completely new file
        new_file_diff = (
            "--- /dev/null\n"
            "+++ b/new_file.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+new_line1\n"
            "+new_line2\n"
        )
        chain = [{"codebase": base}, {"codebase": {"new_file.py": new_file_diff}}]
        result = reconstruct_codebase(chain)
        assert result["train.py"] == "hello\n"
        assert result["new_file.py"] == "new_line1\nnew_line2\n"
