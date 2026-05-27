"""Tests for Client SDK (Phase 6.2): models, config, snapshot, client lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add the modules path so we can import the SDK directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from modules.lineage.config import ServerConfig, ServerConfigError, load_server_config
from modules.lineage.connector import Connector, ConnectorFactory, ServerError
from modules.lineage.models import (
    HealthResponse,
    PostRequest,
    PostResponse,
    PreRequest,
    PreResponse,
)
from modules.lineage.snapshot import (
    FileTooLargeError,
    capture_codebase,
    content_hash,
)
from modules.lineage.client import (
    ExecutionContext,
    LineageClient,
    LineageClientError,
    _find_project_root,
    _load_experiment_yml,
    _save_experiment_yml,
)


# ─── MODELS TESTS ─────────────────────────────────────────────────────────────


class TestModels:
    """Verify Pydantic payload models."""

    def test_pre_request_defaults(self):
        req = PreRequest(experiment_name="test")
        assert req.experiment_name == "test"
        assert req.experiment_uri is None
        assert req.codebase == {}
        assert req.model_uri == ""

    def test_pre_request_full(self):
        req = PreRequest(
            experiment_name="sft-run",
            experiment_uri="/home/user/project",
            base_experiment_id="abc-123",
            model_uri="/nfs/llama-7b",
            model_id="llama-7b",
            codebase={"train.py": "import torch"},
        )
        assert req.codebase == {"train.py": "import torch"}
        assert req.model_id == "llama-7b"

    def test_pre_response(self):
        resp = PreResponse(
            experiment_id="exp-001",
            strategy="BRANCH",
            base=False,
            description="Branch from exp-000",
            changed_files=["train.py"],
        )
        assert resp.strategy == "BRANCH"
        assert resp.changed_files == ["train.py"]

    def test_post_request(self):
        req = PostRequest(
            experiment_id="exp-001",
            status="COMPLETED",
            metrics_uri="/logs/metrics.json",
        )
        assert req.status == "COMPLETED"

    def test_post_response(self):
        resp = PostResponse(experiment_id="exp-001", status="COMPLETED")
        assert resp.acknowledged is True

    def test_health_response(self):
        resp = HealthResponse(status="ok", version="0.1.0", neo4j_connected=True)
        assert resp.neo4j_connected is True


# ─── CONFIG TESTS ──────────────────────────────────────────────────────────────


class TestServerConfig:
    """Verify server config loading from .lineage/server.yml."""

    def test_load_valid_config(self, tmp_path: Path):
        lineage_dir = tmp_path / ".lineage"
        lineage_dir.mkdir()
        (lineage_dir / "server.yml").write_text(
            "url: http://gpu-server:8000\nprotocol: http\ntimeout: 15\nretries: 2\nblocking: true\n"
        )
        config = load_server_config(tmp_path)
        assert config.url == "http://gpu-server:8000"
        assert config.protocol == "http"
        assert config.timeout == 15
        assert config.retries == 2
        assert config.blocking is True

    def test_load_defaults(self, tmp_path: Path):
        lineage_dir = tmp_path / ".lineage"
        lineage_dir.mkdir()
        (lineage_dir / "server.yml").write_text("url: http://localhost:8000\n")
        config = load_server_config(tmp_path)
        assert config.timeout == 30
        assert config.retries == 3
        assert config.blocking is True

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(ServerConfigError, match="not found"):
            load_server_config(tmp_path)

    def test_invalid_yaml_raises(self, tmp_path: Path):
        lineage_dir = tmp_path / ".lineage"
        lineage_dir.mkdir()
        (lineage_dir / "server.yml").write_text("url: [invalid yaml\n")
        with pytest.raises(ServerConfigError, match="Invalid YAML"):
            load_server_config(tmp_path)

    def test_invalid_protocol_raises(self, tmp_path: Path):
        lineage_dir = tmp_path / ".lineage"
        lineage_dir.mkdir()
        (lineage_dir / "server.yml").write_text("url: http://x\nprotocol: websocket\n")
        with pytest.raises(ServerConfigError, match="Invalid server config"):
            load_server_config(tmp_path)


# ─── SNAPSHOT TESTS ────────────────────────────────────────────────────────────


class TestClientSnapshot:
    """Verify client-side codebase capture."""

    def test_captures_root_py_and_yml(self, tmp_path: Path):
        (tmp_path / "train.py").write_text("import torch")
        (tmp_path / "config.yml").write_text("model: llama")
        (tmp_path / "readme.md").write_text("# Skip this")

        files = capture_codebase(tmp_path)
        assert "train.py" in files
        assert "config.yml" in files
        assert "readme.md" not in files

    def test_captures_modules_recursive(self, tmp_path: Path):
        mod = tmp_path / "modules" / "utils"
        mod.mkdir(parents=True)
        (mod / "helper.py").write_text("def h(): pass")
        (mod / "data.json").write_text("{}")

        files = capture_codebase(tmp_path)
        assert "modules/utils/helper.py" in files
        assert "modules/utils/data.json" not in files

    def test_captures_lineage_folder(self, tmp_path: Path):
        lin = tmp_path / ".lineage"
        lin.mkdir()
        (lin / "experiment.yml").write_text("id: null")
        (lin / "server.yml").write_text("url: http://x")

        files = capture_codebase(tmp_path)
        assert ".lineage/experiment.yml" in files
        assert ".lineage/server.yml" in files

    def test_excludes_dot_folders(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "lib.py").write_text("nope")

        files = capture_codebase(tmp_path)
        assert ".venv/lib.py" not in files

    def test_file_too_large_raises(self, tmp_path: Path):
        big = tmp_path / "big.py"
        big.write_text("x" * (10 * 1024 * 1024 + 1))
        with pytest.raises(FileTooLargeError):
            capture_codebase(tmp_path)

    def test_content_hash_deterministic(self):
        files = {"a.py": "hello", "b.py": "world"}
        assert content_hash(files) == content_hash(files)

    def test_content_hash_changes(self):
        f1 = {"a.py": "hello"}
        f2 = {"a.py": "world"}
        assert content_hash(f1) != content_hash(f2)


# ─── CONNECTOR TESTS ──────────────────────────────────────────────────────────


class MockConnector:
    """Mock connector for testing."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.pre_calls: list[PreRequest] = []
        self.post_calls: list[PostRequest] = []

    def health(self) -> HealthResponse:
        return HealthResponse(status="ok", version="test", neo4j_connected=True)

    def send_pre(self, request: PreRequest) -> PreResponse:
        self.pre_calls.append(request)
        return PreResponse(
            experiment_id="mock-exp-001",
            strategy="NEW",
            base=True,
            description="Auto: NEW experiment",
            changed_files=[],
        )

    def send_post(self, request: PostRequest) -> PostResponse:
        self.post_calls.append(request)
        return PostResponse(experiment_id=request.experiment_id, status=request.status)

    def close(self) -> None:
        pass


class TestConnectorFactory:
    """Verify connector factory registration and creation."""

    def test_register_and_create(self):
        # Clean state
        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", MockConnector)

        config = ServerConfig(url="http://localhost:8000", protocol="http")
        connector = ConnectorFactory.create(config)
        assert isinstance(connector, MockConnector)

    def test_unknown_protocol_raises(self):
        ConnectorFactory._registry.clear()
        config = ServerConfig(url="http://x", protocol="http")
        with pytest.raises(ValueError, match="Unknown protocol"):
            ConnectorFactory.create(config)

    def test_server_error(self):
        err = ServerError(status_code=422, detail="Invalid payload")
        assert "422" in str(err)
        assert "Invalid payload" in str(err)


# ─── CLIENT TESTS ──────────────────────────────────────────────────────────────


class TestLineageClient:
    """Verify LineageClient PRE/POST lifecycle."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        """Create a minimal project structure for testing."""
        lineage = tmp_path / ".lineage"
        lineage.mkdir()
        (lineage / "server.yml").write_text(
            "url: http://localhost:8000\nprotocol: http\ntimeout: 5\nretries: 1\nblocking: true\n"
        )
        (lineage / "experiment.yml").write_text(yaml.dump({
            "experiment": {
                "id": None,
                "previous_experiment_id": None,
                "base_experiment_id": None,
                "base": True,
                "name": "test-exp",
                "description": None,
                "uri": None,
                "status": None,
            }
        }))
        (tmp_path / "train.py").write_text("import torch\ntorch.train()")
        (tmp_path / "config.yml").write_text("model:\n  name: llama")
        return tmp_path

    @pytest.fixture(autouse=True)
    def register_mock_connector(self):
        """Register mock connector before each test."""
        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", MockConnector)
        yield
        ConnectorFactory._registry.clear()

    def test_find_project_root(self, project: Path):
        # From project root itself
        root = _find_project_root(project)
        assert root == project.resolve()

    def test_find_project_root_from_subdirectory(self, project: Path):
        sub = project / "modules" / "utils"
        sub.mkdir(parents=True)
        root = _find_project_root(sub)
        assert root == project.resolve()

    def test_find_project_root_missing_raises(self, tmp_path: Path):
        with pytest.raises(LineageClientError, match="No .lineage/"):
            _find_project_root(tmp_path)

    def test_load_experiment_yml(self, project: Path):
        data = _load_experiment_yml(project)
        assert data["name"] == "test-exp"
        assert data["id"] is None

    def test_save_experiment_yml(self, project: Path):
        _save_experiment_yml(project, {"id": "abc", "name": "test", "status": "RUNNING"})
        data = _load_experiment_yml(project)
        assert data["id"] == "abc"
        assert data["status"] == "RUNNING"

    def test_pre_execution_success(self, project: Path):
        client = LineageClient(project_root=project)
        ctx = client.pre_execution()

        assert ctx is not None
        assert ctx.experiment_id == "mock-exp-001"
        assert ctx.strategy == "NEW"

        # Verify local state was updated
        data = _load_experiment_yml(project)
        assert data["id"] == "mock-exp-001"
        assert data["status"] == "RUNNING"

        client.close()

    def test_pre_execution_sends_codebase(self, project: Path):
        client = LineageClient(project_root=project)
        client.pre_execution()

        # Get the mock connector to inspect calls
        connector = client._connector
        assert len(connector.pre_calls) == 1
        req = connector.pre_calls[0]
        assert "train.py" in req.codebase
        assert "config.yml" in req.codebase
        assert ".lineage/experiment.yml" in req.codebase

        client.close()

    def test_post_execution_success(self, project: Path):
        client = LineageClient(project_root=project)
        ctx = client.pre_execution()
        client.post_execution(ctx, status="COMPLETED", metrics_uri="/logs/m.json")

        connector = client._connector
        assert len(connector.post_calls) == 1
        assert connector.post_calls[0].status == "COMPLETED"
        assert connector.post_calls[0].metrics_uri == "/logs/m.json"

        # Local state updated
        data = _load_experiment_yml(project)
        assert data["status"] == "COMPLETED"

        client.close()

    def test_pre_execution_connection_error_blocking_exits(self, project: Path):
        """Blocking mode + connection failure → sys.exit(10)."""

        class FailConnector:
            def __init__(self, config): pass
            def send_pre(self, req): raise ConnectionError("refused")
            def send_post(self, req): pass
            def health(self): pass
            def close(self): pass

        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", FailConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 10

    def test_pre_execution_connection_error_nonblocking_returns_none(self, project: Path):
        """Non-blocking mode + connection failure → returns None."""

        class FailConnector:
            def __init__(self, config): pass
            def send_pre(self, req): raise ConnectionError("refused")
            def send_post(self, req): pass
            def health(self): pass
            def close(self): pass

        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", FailConnector)

        # Override server config to non-blocking
        lineage = project / ".lineage"
        (lineage / "server.yml").write_text(
            "url: http://localhost:8000\nprotocol: http\nblocking: false\nretries: 0\n"
        )

        client = LineageClient(project_root=project)
        ctx = client.pre_execution()
        assert ctx is None

    def test_pre_execution_server_error_blocking_exits(self, project: Path):
        """Server returns error in blocking mode → sys.exit(9)."""

        class ErrorConnector:
            def __init__(self, config): pass
            def send_pre(self, req): raise ServerError(422, "bad payload")
            def send_post(self, req): pass
            def health(self): pass
            def close(self): pass

        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", ErrorConnector)

        client = LineageClient(project_root=project)
        with pytest.raises(SystemExit) as exc_info:
            client.pre_execution()
        assert exc_info.value.code == 9


# ─── DECORATOR TESTS ──────────────────────────────────────────────────────────


class TestLineageTrackerDecorator:
    """Verify the @lineage_tracker decorator."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        lineage = tmp_path / ".lineage"
        lineage.mkdir()
        (lineage / "server.yml").write_text(
            "url: http://localhost:8000\nprotocol: http\ntimeout: 5\nretries: 0\nblocking: true\n"
        )
        (lineage / "experiment.yml").write_text(yaml.dump({
            "experiment": {
                "id": None,
                "name": "decorator-test",
                "uri": None,
                "status": None,
                "base": True,
                "base_experiment_id": None,
                "previous_experiment_id": None,
                "description": None,
            }
        }))
        (tmp_path / "train.py").write_text("pass")
        (tmp_path / "config.yml").write_text("model: x")
        return tmp_path

    @pytest.fixture(autouse=True)
    def register_mock(self):
        ConnectorFactory._registry.clear()
        ConnectorFactory.register("http", MockConnector)
        yield
        ConnectorFactory._registry.clear()

    def test_decorator_wraps_function(self, project: Path):
        from modules.lineage import lineage_tracker

        config_path = str(project / "config.yml")

        @lineage_tracker()
        def my_train(config_path: str):
            return "trained"

        result = my_train(config_path=config_path)
        assert result == "trained"

        # Verify state was updated
        data = _load_experiment_yml(project)
        assert data["status"] == "COMPLETED"
        assert data["id"] == "mock-exp-001"

    def test_decorator_handles_failure(self, project: Path):
        from modules.lineage import lineage_tracker

        config_path = str(project / "config.yml")

        @lineage_tracker()
        def failing_train(config_path: str):
            raise RuntimeError("OOM")

        with pytest.raises(RuntimeError, match="OOM"):
            failing_train(config_path=config_path)

        data = _load_experiment_yml(project)
        assert data["status"] == "FAILED"
