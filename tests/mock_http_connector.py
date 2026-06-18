"""Mock HTTP transport for testing client-server communication.

Provides FastAPITestTransport and TestHttpConnector to enable testing
without actual network or external services.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

import httpx
import sys

# Add setups/_base to path so we can import client SDK
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "graph_lineage" / "setups" / "_base"))

from fastapi.testclient import TestClient
from modules.lineage.http_connector import HttpConnector
from modules.lineage.config import ServerConfig
from graph_lineage.server.app import app

from tests.mock_neo4j import InMemoryNeo4jTracker


class FastAPITestTransport(httpx.BaseTransport):
    """HTTPX transport that routes requests to FastAPI TestClient.

    Intercepts httpx requests and routes them to FastAPI's TestClient,
    which handles server logic in-memory without actual HTTP.
    """

    def __init__(self, mock_db: InMemoryNeo4jTracker, logger: logging.Logger | None = None):
        """Initialize transport.

        Args:
            mock_db: InMemoryNeo4jTracker to inject into server context
            logger: Optional logger for request/response logging
        """
        self._test_client = TestClient(app)
        self._mock_db = mock_db
        self._logger = logger or logging.getLogger(__name__)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Route httpx request to TestClient with mocked Neo4j operations.

        Args:
            request: httpx.Request to handle

        Returns:
            httpx.Response from server
        """
        # Log request
        self._logger.info(f"→ {request.method} {request.url.path}")
        if request.content:
            try:
                body = json.loads(request.content)
                self._logger.debug(f"  Body: {json.dumps(body, indent=2)}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._logger.debug(f"  Body: {request.content[:100]}")

        # Patch all Neo4j operations to use our in-memory tracker
        with self._patch_neo4j_operations():
            path = request.url.path
            method = request.method.upper()
            headers = dict(request.headers)
            content = request.content

            # Route to TestClient
            if method == "GET":
                resp = self._test_client.get(path, headers=headers)
            elif method == "POST":
                resp = self._test_client.post(path, content=content, headers=headers)
            elif method == "PUT":
                resp = self._test_client.put(path, content=content, headers=headers)
            elif method == "DELETE":
                resp = self._test_client.delete(path, headers=headers)
            else:
                resp = self._test_client.request(method, path, content=content, headers=headers)

            # Convert TestClient response to httpx.Response
            result = httpx.Response(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                content=resp.content,
            )

            # Log response
            self._logger.info(f"← {result.status_code} {request.method} {request.url.path}")
            if result.content:
                try:
                    body = json.loads(result.content)
                    self._logger.debug(f"  Response: {json.dumps(body, indent=2)}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._logger.debug(f"  Response: {result.content[:100]}")

            return result

    @contextmanager
    def _patch_neo4j_operations(self):
        """Context manager that patches all Neo4j operations in the server.

        Yields the patches so they're active during request handling.
        """
        patches = [
            patch(
                "graph_lineage.server.app.create_experiment_node",
                side_effect=self._mock_db.create_experiment_node,
            ),
            patch(
                "graph_lineage.server.app.find_experiment_by_id",
                side_effect=self._mock_db.find_experiment_by_id,
            ),
            patch(
                "graph_lineage.server.app.find_parent_experiment",
                side_effect=self._mock_db.find_parent_experiment,
            ),
            patch(
                "graph_lineage.server.app.create_edge",
                side_effect=self._mock_db.create_edge,
            ),
            patch(
                "graph_lineage.server.app.create_checkpoint_node",
                side_effect=self._mock_db.create_checkpoint_node,
            ),
            patch(
                "graph_lineage.server.app.create_checkpoint_edge",
                side_effect=self._mock_db.create_checkpoint_edge,
            ),
            patch(
                "graph_lineage.server.app.update_experiment_status",
                side_effect=self._mock_db.update_experiment_status,
            ),
        ]

        # Start all patches
        active_patches = [p.start() for p in patches]
        try:
            yield
        finally:
            # Stop all patches
            for p in patches:
                p.stop()


class TestHttpConnector(HttpConnector):
    """HttpConnector for testing that uses FastAPITestTransport.

    Integrates with LineageClient and routes all HTTP requests to
    the mock transport, enabling full E2E testing without network.
    """

    def __init__(self, config: ServerConfig, mock_db: InMemoryNeo4jTracker, logger: logging.Logger | None = None):
        """Initialize test connector.

        Args:
            config: ServerConfig with server details
            mock_db: InMemoryNeo4jTracker to inject into server
            logger: Optional logger for request/response logging
        """
        self._config = config
        self._base_url = config.url.rstrip("/")
        self._mock_db = mock_db
        self._logger = logger or logging.getLogger(__name__)

        # Create httpx client with mock transport
        self._client = httpx.Client(
            base_url=self._base_url,
            transport=FastAPITestTransport(mock_db, logger=self._logger),
        )
