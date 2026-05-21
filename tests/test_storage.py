"""Tests for storage abstraction layer."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from graph_lineage.storage.local_provider import LocalStorageProvider
from graph_lineage.storage.resolver import StorageResolver


# ── LocalStorageProvider ──────────────────────────────────────────


class TestLocalStorageProvider:
    """Unit tests for LocalStorageProvider."""

    @pytest.fixture
    def tmp(self, tmp_path: Path) -> LocalStorageProvider:
        """Provider rooted at tmp_path."""
        return LocalStorageProvider(base_path=str(tmp_path))

    @pytest.fixture
    def abs_provider(self) -> LocalStorageProvider:
        """Provider with no base_path (absolute paths)."""
        return LocalStorageProvider()

    # ── exists ──

    def test_exists_true(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "file.txt").write_text("hello")
        assert tmp.exists("file.txt") is True

    def test_exists_false(self, tmp: LocalStorageProvider):
        assert tmp.exists("missing.txt") is False

    # ── read/write text ──

    def test_write_read_text(self, tmp: LocalStorageProvider):
        tmp.write_text("data/out.txt", "content here")
        assert tmp.read_text("data/out.txt") == "content here"

    def test_read_text_missing_raises(self, tmp: LocalStorageProvider):
        with pytest.raises(FileNotFoundError):
            tmp.read_text("nope.txt")

    # ── read/write bytes ──

    def test_write_read_bytes(self, tmp: LocalStorageProvider):
        data = b"\x00\x01\x02\xff"
        tmp.write_bytes("bin.dat", data)
        assert tmp.read_bytes("bin.dat") == data

    def test_read_bytes_missing_raises(self, tmp: LocalStorageProvider):
        with pytest.raises(FileNotFoundError):
            tmp.read_bytes("nope.bin")

    # ── write creates parent dirs ──

    def test_write_creates_parents(self, tmp: LocalStorageProvider, tmp_path: Path):
        tmp.write_text("a/b/c/deep.txt", "deep")
        assert (tmp_path / "a" / "b" / "c" / "deep.txt").read_text() == "deep"

    # ── list_files ──

    def test_list_files(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        (tmp_path / "c.txt").write_text("c")
        result = tmp.list_files(".", "*.py")
        assert len(result) == 2
        assert all(f.endswith(".py") for f in result)

    def test_list_files_empty_dir(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "subdir").mkdir()
        assert tmp.list_files("subdir") == []

    def test_list_files_nonexistent_dir(self, tmp: LocalStorageProvider):
        assert tmp.list_files("nope") == []

    # ── walk ──

    def test_walk_excludes_dotfiles(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "visible.py").write_text("v")
        (tmp_path / ".hidden").write_text("h")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("g")

        files = list(tmp.walk("."))
        names = [os.path.basename(f) for f in files]
        assert "visible.py" in names
        assert ".hidden" not in names
        assert "config" not in names  # inside .git

    def test_walk_includes_dotfiles_when_disabled(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / ".hidden").write_text("h")
        files = list(tmp.walk(".", exclude_dotfiles=False))
        names = [os.path.basename(f) for f in files]
        assert ".hidden" in names

    def test_walk_nonexistent_dir(self, tmp: LocalStorageProvider):
        files = list(tmp.walk("nope"))
        assert files == []

    # ── is_dir ──

    def test_is_dir_true(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "subdir").mkdir()
        assert tmp.is_dir("subdir") is True

    def test_is_dir_false_on_file(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "file.txt").write_text("f")
        assert tmp.is_dir("file.txt") is False

    # ── is_writable ──

    def test_is_writable_existing_file(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "w.txt").write_text("w")
        assert tmp.is_writable("w.txt") is True

    def test_is_writable_new_file_in_existing_dir(self, tmp: LocalStorageProvider):
        assert tmp.is_writable("new_file.txt") is True

    # ── backup ──

    def test_backup_creates_copy(self, tmp: LocalStorageProvider, tmp_path: Path):
        (tmp_path / "orig.txt").write_text("original")
        backup_path = tmp.backup("orig.txt")
        assert backup_path is not None
        assert Path(backup_path).exists()
        assert Path(backup_path).read_text() == "original"

    def test_backup_missing_returns_none(self, tmp: LocalStorageProvider):
        assert tmp.backup("missing.txt") is None

    # ── absolute paths with no base ──

    def test_absolute_provider(self, abs_provider: LocalStorageProvider):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abs test")
            f.flush()
            path = f.name
        try:
            assert abs_provider.exists(path) is True
            assert abs_provider.read_text(path) == "abs test"
        finally:
            os.unlink(path)


# ── StorageResolver ───────────────────────────────────────────────


class TestStorageResolver:
    """Unit tests for StorageResolver."""

    def test_default_resolves_to_local(self):
        resolver = StorageResolver()
        provider, path = resolver.resolve("/some/path/file.txt")
        assert isinstance(provider, LocalStorageProvider)
        assert path == "/some/path/file.txt"

    def test_exists_delegates(self, tmp_path: Path):
        (tmp_path / "test.txt").write_text("hi")
        resolver = StorageResolver()
        assert resolver.exists(str(tmp_path / "test.txt")) is True
        assert resolver.exists(str(tmp_path / "nope.txt")) is False

    def test_read_write_delegates(self, tmp_path: Path):
        resolver = StorageResolver()
        target = str(tmp_path / "rw.txt")
        resolver.write_text(target, "hello resolver")
        assert resolver.read_text(target) == "hello resolver"

    def test_validate_uris_all_valid(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        resolver = StorageResolver()
        results = resolver.validate_uris([
            str(tmp_path / "a.txt"),
            str(tmp_path / "b.txt"),
        ])
        assert all(v is None for v in results.values())

    def test_validate_uris_missing(self, tmp_path: Path):
        resolver = StorageResolver()
        missing = str(tmp_path / "no_such_dir" / "ghost.txt")
        results = resolver.validate_uris([missing])
        assert results[missing] is not None  # error message

    def test_config_file_loading(self, tmp_path: Path):
        # Create storage config
        config = tmp_path / ".storage-config.yml"
        mount_dir = tmp_path / "mounted"
        mount_dir.mkdir()
        (mount_dir / "data.txt").write_text("mounted data")

        config.write_text(f"""
mounts:
  - prefix: "/mnt/shared"
    provider: "local"
    base_path: "{mount_dir}"
default_provider: "local"
""")
        resolver = StorageResolver(config_path=str(config))
        provider, path = resolver.resolve("/mnt/shared/data.txt")
        assert isinstance(provider, LocalStorageProvider)
        assert provider.read_text(path) == "mounted data"

    def test_config_file_missing_warns(self, tmp_path: Path):
        """Missing config → fallback to local, no crash."""
        resolver = StorageResolver(config_path=str(tmp_path / "nope.yml"))
        provider, path = resolver.resolve("/any/path")
        assert isinstance(provider, LocalStorageProvider)
