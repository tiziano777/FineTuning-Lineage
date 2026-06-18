"""Shared test fixtures for lineage system tests.

Provides:
- mock_neo4j: InMemoryNeo4jTracker instance
- test_project: Minimal project structure for testing
- lineage_client: LineageClient connected to mock server
- integration_client: FastAPI TestClient with mocked Neo4j
- http_logger: Logger for HTTP communication tests
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

# Add setups/_base to path for client SDK imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from modules.lineage.client import LineageClient
from modules.lineage.config import ServerConfig
from graph_lineage.server.app import app

from tests.mock_neo4j import InMemoryNeo4jTracker
from tests.mock_http_connector import TestHttpConnector


# ─────────────────────────────────────────────────────────────────────────────
# Mock Database Fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_neo4j():
    """Provide InMemoryNeo4jTracker for all tests.

    Yields a tracker instance and resets it after each test for isolation.
    """
    tracker = InMemoryNeo4jTracker()
    yield tracker
    tracker.reset()


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Communication Logger Fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def http_logger(request) -> logging.Logger:
    """Create a logger for HTTP communication tests.

    Creates per-test log file at tests/http_test_<testname>.log
    to capture all HTTP requests/responses for each test independently.
    Provides both file and console output with DEBUG level for details.

    Args:
        request: pytest request object for test name

    Yields:
        Configured logger instance
    """
    # Create per-test log file name
    test_name = request.node.name.replace("/", "_").replace("::", "_")
    log_file = Path(__file__).parent / f"http_test_{test_name}.log"

    logger = logging.getLogger(f"http_connector_test_{test_name}")
    logger.setLevel(logging.DEBUG)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # File handler - DEBUG level for full details
    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # Console handler - INFO level for summary
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    yield logger

    # Cleanup
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Test Project Fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def test_project(tmp_path: Path) -> Path:
    """Create a minimal test project structure.

    Creates:
    - .lineage/experiment.yml - experiment metadata
    - .lineage/server.yml - server connection config
    - config.yml - training configuration
    - train.py - training script
    - prepare.py - data preparation script
    - requirements.txt - dependencies
    - modules/utils/helper.py - utility module

    Args:
        tmp_path: Pytest's temporary directory fixture

    Returns:
        Path to created project root
    """
    project = tmp_path / "test-project"
    project.mkdir()

    # Create .lineage/ directory
    lineage = project / ".lineage"
    lineage.mkdir()

    # Create experiment.yml (system-managed metadata)
    (lineage / "experiment.yml").write_text(
        yaml.dump({
            "experiment": {
                "id": None,
                "name": "test-experiment",
                "uri": str(project),
                "description": None,
                "status": None,
                "strategy": None,
                "base": True,
                "previous_experiment_id": None,
                "base_experiment_id": None,
                "checkpoint_resume_from": None,
                "created_at": None,
                "updated_at": None,
            }
        })
    )

    # Create server.yml (connection config)
    (lineage / "server.yml").write_text(
        yaml.dump({
            "url": "http://localhost:8000",
            "protocol": "http",
            "timeout": 10,
            "retries": 0,
            "blocking": True,
        })
    )

    # Create config.yml (training config)
    (project / "config.yml").write_text(
        yaml.dump({
            "experiment": {
                "name": "test-train",
                "uri": str(project),
            },
            "model": {
                "model_uri": "/nfs/llama-7b",
                "model_id": "llama-7b-base",
                "training": {
                    "learning_rate": 1e-4,
                    "per_device_train_batch_size": 1,
                    "num_train_epochs": 1,
                },
                "dataset": {
                    "cache_dir": str(project / "cache"),
                },
            },
            "output": {
                "output_dir": str(project / "output"),
                "metrics_uri": "/logs/${experiment.id}/metrics.json",
            },
        })
    )

    # Create train.py (training entry point)
    (project / "train.py").write_text(
        """from modules.lineage import lineage_tracker

@lineage_tracker()
def train(config_path: str):
    \"\"\"Minimal training function for testing.\"\"\"
    print(f"Training with {config_path}")
    return "success"

if __name__ == "__main__":
    train("config.yml")
"""
    )

    # Create prepare.py (data preparation)
    (project / "prepare.py").write_text(
        """def prepare(config_path: str):
    \"\"\"Prepare minimal training dataset.\"\"\"
    print(f"Preparing dataset for {config_path}")

if __name__ == "__main__":
    prepare("config.yml")
"""
    )

    # Create requirements.txt
    (project / "requirements.txt").write_text(
        "pyyaml>=6.0\n"
    )

    # Create modules/utils/ structure
    modules = project / "modules" / "utils"
    modules.mkdir(parents=True)
    (modules / "__init__.py").write_text("")
    (modules / "helper.py").write_text(
        """def load_data():
    \"\"\"Load training data.\"\"\"
    return []
"""
    )

    return project


# ─────────────────────────────────────────────────────────────────────────────
# Lineage Client Fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def lineage_client(test_project: Path, mock_neo4j: InMemoryNeo4jTracker, http_logger: logging.Logger) -> LineageClient:
    """Create LineageClient connected to mock server.

    Configures the client to use TestHttpConnector instead of real HTTP,
    allowing full integration tests without network.

    Args:
        test_project: Fixture providing test project path
        mock_neo4j: Fixture providing mock database
        http_logger: Fixture providing logger for HTTP communication

    Yields:
        Configured LineageClient instance
    """
    # Create server config pointing to localhost
    config = ServerConfig(url="http://localhost:8000", protocol="http", timeout=10)

    # Create client with test project root
    client = LineageClient(project_root=test_project)

    # Replace connector with test version using mock transport with logger
    client._connector = TestHttpConnector(config, mock_neo4j, logger=http_logger)

    yield client

    # Cleanup
    client.close()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Test Client with Mocked Neo4j
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def integration_client(mock_neo4j: InMemoryNeo4jTracker) -> TestClient:
    """Create FastAPI TestClient with mocked Neo4j operations.

    Patches all Neo4j CRUD functions to use the in-memory tracker,
    enabling direct testing of server endpoints.

    Args:
        mock_neo4j: Fixture providing mock database

    Yields:
        FastAPI TestClient with active Neo4j patches
    """
    patches = [
        patch(
            "graph_lineage.server.app.create_experiment_node",
            side_effect=mock_neo4j.create_experiment_node,
        ),
        patch(
            "graph_lineage.server.app.find_experiment_by_id",
            side_effect=mock_neo4j.find_experiment_by_id,
        ),
        patch(
            "graph_lineage.server.app.find_parent_experiment",
            side_effect=mock_neo4j.find_parent_experiment,
        ),
        patch(
            "graph_lineage.server.app.create_edge",
            side_effect=mock_neo4j.create_edge,
        ),
        patch(
            "graph_lineage.server.app.create_checkpoint_node",
            side_effect=mock_neo4j.create_checkpoint_node,
        ),
        patch(
            "graph_lineage.server.app.create_checkpoint_edge",
            side_effect=mock_neo4j.create_checkpoint_edge,
        ),
        patch(
            "graph_lineage.server.app.update_experiment_status",
            side_effect=mock_neo4j.update_experiment_status,
        ),
    ]

    # Start all patches
    for p in patches:
        p.start()

    yield TestClient(app)

    # Stop all patches
    for p in patches:
        p.stop()
