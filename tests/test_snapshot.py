"""Tests for CodebaseSnapshot model and new scan logic."""

import pytest
from pathlib import Path
from pydantic import ValidationError

from graph_lineage.diff.snapshot import CodebaseSnapshot, capture_snapshot, FileTooLargeError


class TestCodebaseSnapshot:
    """Verify CodebaseSnapshot is frozen and captures project files."""

    def test_frozen_immutable(self):
        """Test 1: CodebaseSnapshot is frozen -- assigning raises ValidationError."""
        snap = CodebaseSnapshot(files={"config.yaml": "test"})
        with pytest.raises(ValidationError):
            snap.files = {"other": "value"}

    def test_capture_snapshot_reads_root_files(self, tmp_path: Path):
        """Test 2: capture_snapshot reads root-level *.py, *.txt, *.yml files."""
        (tmp_path / "config.yml").write_text("cfg_content")
        (tmp_path / "prepare.py").write_text("prep_content")
        (tmp_path / "train.py").write_text("train_content")
        (tmp_path / "requirements.txt").write_text("req_content")

        snap = capture_snapshot(tmp_path)
        assert snap.files["config.yml"] == "cfg_content"
        assert snap.files["prepare.py"] == "prep_content"
        assert snap.files["train.py"] == "train_content"
        assert snap.files["requirements.txt"] == "req_content"

    def test_missing_files_not_in_snapshot(self, tmp_path: Path):
        """Test 3: Missing files simply not present in snapshot dict."""
        (tmp_path / "config.yml").write_text("only_config")
        # Other files missing — snapshot only has what exists

        snap = capture_snapshot(tmp_path)
        assert snap.files["config.yml"] == "only_config"
        assert "prepare.py" not in snap.files
        assert "train.py" not in snap.files

    def test_file_hash_returns_sha256(self):
        """Test 4: snapshot.file_hash(filename) returns SHA-256 hex digest."""
        import hashlib
        content = "hello world"
        expected = hashlib.sha256(content.encode()).hexdigest()

        snap = CodebaseSnapshot(files={"config.yml": content})
        assert snap.file_hash("config.yml") == expected

    def test_hashes_returns_all_captured_files(self, tmp_path: Path):
        """Test 5: snapshot.hashes() returns dict of all captured file hashes."""
        (tmp_path / "config.yml").write_text("a")
        (tmp_path / "prepare.py").write_text("b")
        (tmp_path / "train.py").write_text("c")
        (tmp_path / "requirements.txt").write_text("d")

        snap = capture_snapshot(tmp_path)
        h = snap.hashes()
        assert len(h) == 4
        # Each value is a 64-char hex string (SHA-256)
        for v in h.values():
            assert len(v) == 64

    def test_modules_recursive_scan(self, tmp_path: Path):
        """Test 6: modules/ folder is scanned recursively for *.py and *.yml."""
        modules = tmp_path / "modules" / "utils"
        modules.mkdir(parents=True)
        (modules / "helper.py").write_text("def help(): pass")
        (modules / "config.yml").write_text("key: val")
        (modules / "data.json").write_text("{}")  # Should be skipped

        snap = capture_snapshot(tmp_path)
        assert "modules/utils/helper.py" in snap.files
        assert "modules/utils/config.yml" in snap.files
        assert "modules/utils/data.json" not in snap.files

    def test_dot_folders_excluded(self, tmp_path: Path):
        """Test 7: Dot-folders (except .lineage/) are excluded."""
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("venv stuff")
        (tmp_path / ".cache").mkdir()
        (tmp_path / ".cache" / "data.py").write_text("cache")

        snap = capture_snapshot(tmp_path)
        assert ".venv/lib.py" not in snap.files
        assert ".cache/data.py" not in snap.files

    def test_lineage_folder_included(self, tmp_path: Path):
        """Test 8: .lineage/ folder IS included."""
        lineage = tmp_path / ".lineage"
        lineage.mkdir()
        (lineage / "experiment.yml").write_text("id: null")
        (lineage / "server.yml").write_text("url: http://localhost")

        snap = capture_snapshot(tmp_path)
        assert ".lineage/experiment.yml" in snap.files
        assert ".lineage/server.yml" in snap.files

    def test_dot_files_at_root_excluded(self, tmp_path: Path):
        """Test 9: Dot-files at root level are excluded."""
        (tmp_path / ".env").write_text("SECRET=x")
        (tmp_path / ".gitignore").write_text("*.pyc")
        (tmp_path / "train.py").write_text("main()")

        snap = capture_snapshot(tmp_path)
        assert ".env" not in snap.files
        assert ".gitignore" not in snap.files
        assert "train.py" in snap.files

    def test_file_too_large_raises_error(self, tmp_path: Path):
        """Test 10: File > 10MB raises FileTooLargeError."""
        big_file = tmp_path / "huge.py"
        # Write just over 10MB
        big_file.write_text("x" * (10 * 1024 * 1024 + 1))

        with pytest.raises(FileTooLargeError) as exc_info:
            capture_snapshot(tmp_path)
        assert "huge.py" in str(exc_info.value)
        assert "10MB" in str(exc_info.value)

    def test_content_hash_deterministic(self):
        """Test 11: content_hash() is deterministic for same content."""
        snap1 = CodebaseSnapshot(files={"a.py": "hello", "b.py": "world"})
        snap2 = CodebaseSnapshot(files={"a.py": "hello", "b.py": "world"})
        assert snap1.content_hash() == snap2.content_hash()

    def test_content_hash_changes_with_content(self):
        """Test 12: content_hash() changes when file content changes."""
        snap1 = CodebaseSnapshot(files={"a.py": "hello"})
        snap2 = CodebaseSnapshot(files={"a.py": "world"})
        assert snap1.content_hash() != snap2.content_hash()

    def test_non_tracked_extensions_skipped(self, tmp_path: Path):
        """Test 13: Files with non-tracked extensions at root are skipped."""
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "model.bin").write_bytes(b"\x00" * 100)
        (tmp_path / "script.py").write_text("pass")

        snap = capture_snapshot(tmp_path)
        assert "readme.md" not in snap.files
        assert "data.json" not in snap.files
        assert "model.bin" not in snap.files
        assert "script.py" in snap.files
