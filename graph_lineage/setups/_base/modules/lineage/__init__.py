"""Lineage Client SDK — Public API."""

from .client import LineageClient, LineageClientError, ExecutionContext
from .config import ServerConfig, ServerConfigError
from .connector import Connector, ConnectorFactory, ServerError
from .models import (
    CheckpointRequest, CheckpointResponse,
    PostRequest, PostResponse,
    PreRequest, PreResponse,
    HealthResponse,
)
from .snapshot import FileTooLargeError, capture_codebase, content_hash
from .tracker import lineage_tracker, LineageCheckpointCallback

# Auto-register built-in connectors
from . import http_connector as _http_connector  # noqa: F401

__all__ = [
    "LineageClient",
    "LineageClientError",
    "ExecutionContext",
    "LineageCheckpointCallback",
    "ServerConfig",
    "ServerConfigError",
    "Connector",
    "ConnectorFactory",
    "ServerError",
    "PreRequest",
    "PreResponse",
    "PostRequest",
    "PostResponse",
    "CheckpointRequest",
    "CheckpointResponse",
    "HealthResponse",
    "FileTooLargeError",
    "capture_codebase",
    "content_hash",
    "lineage_tracker",
]