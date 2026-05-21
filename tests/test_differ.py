"""Tests for Differ module -- diff generation, hashing, change detection."""

from graph_lineage.diff.differ import (
    compute_file_hash,
    compute_unified_diff,
    detect_changes,
    compute_snapshot_diff,
)
from graph_lineage.diff.snapshot import CodebaseSnapshot


class TestComputeFileHash:
    """Verify SHA-256 hash with CRLF normalization."""

    def test_returns_sha256_normalized(self):
        """Test 1: compute_file_hash normalizes CRLF to LF then hashes."""
        import hashlib
        content_crlf = "line1\r\nline2\r\n"
        content_lf = "line1\nline2\n"
        expected = hashlib.sha256(content_lf.encode()).hexdigest()

        assert compute_file_hash(content_crlf) == expected
        assert compute_file_hash(content_lf) == expected


class TestComputeUnifiedDiff:
    """Verify unified diff generation."""

    def test_returns_unified_diff_with_prefixes(self):
        """Test 2: compute_unified_diff returns diff with a/b prefixes."""
        old = "line1\nline2\n"
        new = "line1\nline2_modified\n"
        diff = compute_unified_diff(old, new, "train.py")
        assert "--- a/train.py" in diff
        assert "+++ b/train.py" in diff
        assert "-line2" in diff
        assert "+line2_modified" in diff

    def test_identical_content_empty_diff(self):
        """Test 3: Identical content -> empty diff string."""
        content = "same\ncontent\n"
        diff = compute_unified_diff(content, content, "config.yaml")
        assert diff == ""


class TestDetectChanges:
    """Verify change detection by hash comparison."""

    def test_returns_changed_filenames(self):
        """Test 4: detect_changes returns list of changed filenames."""
        old = {"a.py": "hash1", "b.py": "hash2"}
        new = {"a.py": "hash1", "b.py": "hash_different"}
        assert detect_changes(old, new) == ["b.py"]

    def test_no_changes_empty_list(self):
        """Test 5: No changes -> empty list."""
        hashes = {"a.py": "h1", "b.py": "h2"}
        assert detect_changes(hashes, hashes) == []


class TestComputeSnapshotDiff:
    """Verify snapshot-level diff computation."""

    def test_returns_dict_of_changed_files_only(self):
        """Test 6: compute_snapshot_diff returns {filename: diff} for changed files only."""
        old_snap = CodebaseSnapshot(files={
            "config.yaml": "old_cfg",
            "train.py": "same_train",
        })
        new_snap = CodebaseSnapshot(files={
            "config.yaml": "new_cfg",
            "train.py": "same_train",
        })
        result = compute_snapshot_diff(old_snap, new_snap)
        assert "config.yaml" in result
        assert "train.py" not in result
        assert "--- a/config.yaml" in result["config.yaml"]
