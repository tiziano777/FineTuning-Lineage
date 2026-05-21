"""Tests for CodebaseSnapshot model."""

import pytest
from pathlib import Path
from pydantic import ValidationError

from graph_lineage.diff.snapshot import CodebaseSnapshot, capture_snapshot


class TestCodebaseSnapshot:
    """Verify CodebaseSnapshot is frozen and captures critical files."""

    def test_frozen_immutable(self):
        """Test 1: CodebaseSnapshot is frozen -- assigning raises ValidationError."""
        snap = CodebaseSnapshot(files={"config.yaml": "test"})
        with pytest.raises(ValidationError):
            snap.files = {"other": "value"}

    def test_capture_snapshot_reads_4_files(self, tmp_path: Path):
        """Test 2: capture_snapshot reads 4 critical files into dict."""
        (tmp_path / "config.yaml").write_text("cfg_content")
        (tmp_path / "prepare.py").write_text("prep_content")
        (tmp_path / "train.py").write_text("train_content")
        (tmp_path / "requirements.txt").write_text("req_content")

        snap = capture_snapshot(tmp_path)
        assert snap.files["config.yaml"] == "cfg_content"
        assert snap.files["prepare.py"] == "prep_content"
        assert snap.files["train.py"] == "train_content"
        assert snap.files["requirements.txt"] == "req_content"

    def test_missing_file_stored_as_empty_string(self, tmp_path: Path):
        """Test 3: Missing critical file -> stored as empty string."""
        (tmp_path / "config.yaml").write_text("only_config")
        # Other 3 files missing

        snap = capture_snapshot(tmp_path)
        assert snap.files["config.yaml"] == "only_config"
        assert snap.files["prepare.py"] == ""
        assert snap.files["train.py"] == ""
        assert snap.files["requirements.txt"] == ""

    def test_file_hash_returns_sha256(self):
        """Test 4: snapshot.file_hash(filename) returns SHA-256 hex digest."""
        import hashlib
        content = "hello world"
        expected = hashlib.sha256(content.encode()).hexdigest()

        snap = CodebaseSnapshot(files={"config.yaml": content})
        assert snap.file_hash("config.yaml") == expected

    def test_hashes_returns_all_4(self, tmp_path: Path):
        """Test 5: snapshot.hashes() returns dict of all 4 file hashes."""
        (tmp_path / "config.yaml").write_text("a")
        (tmp_path / "prepare.py").write_text("b")
        (tmp_path / "train.py").write_text("c")
        (tmp_path / "requirements.txt").write_text("d")

        snap = capture_snapshot(tmp_path)
        h = snap.hashes()
        assert len(h) == 4
        assert set(h.keys()) == {"config.yaml", "prepare.py", "train.py", "requirements.txt"}
        # Each value is a 64-char hex string (SHA-256)
        for v in h.values():
            assert len(v) == 64
