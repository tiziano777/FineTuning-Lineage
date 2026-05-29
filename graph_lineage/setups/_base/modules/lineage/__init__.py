"""Lineage Client SDK — easy-to-integrate tracking for training scripts.

Public API:
    - LineageClient: Full client for manual PRE/POST lifecycle
    - lineage_tracker: Decorator that wraps training functions automatically
    - ServerConfig, ServerConfigError: Configuration classes
    - Connector, ConnectorFactory, ServerError: Transport layer
    - PreRequest, PreResponse, PostRequest, PostResponse: Payloads

Usage as decorator:
    from modules.lineage import lineage_tracker

    @lineage_tracker()
    def train(config_path: str):
        ...

Usage as client:
    from modules.lineage import LineageClient

    client = LineageClient(config_path="config.yml")
    ctx = client.pre_execution()
    try:
        train(...)
        client.post_execution(ctx, status="COMPLETED")
    except Exception as e:
        client.post_execution(ctx, status="FAILED", exit_message=str(e))
        raise
    finally:
        client.close()
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from .client import ExecutionContext, LineageClient, LineageClientError
from .config import ServerConfig, ServerConfigError
from .connector import Connector, ConnectorFactory, ServerError
from .models import (
    CheckpointRequest,
    CheckpointResponse,
    HealthResponse,
    PostRequest,
    PostResponse,
    PreRequest,
    PreResponse,
)
from .snapshot import FileTooLargeError, capture_codebase, content_hash

# Auto-register built-in connectors
from . import http_connector as _http_connector  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = [
    "LineageClient",
    "LineageClientError",
    "LineageCheckpointCallback",
    "ExecutionContext",
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


def LineageCheckpointCallback(*args, **kwargs):
    """Lazy accessor — avoids importing transformers at module load time."""
    from .callbacks import LineageCheckpointCallback as _Cls
    return _Cls(*args, **kwargs)


def lineage_tracker(config_path_arg: int = 0, capture_checkpoints: bool = False) -> Callable:
    """Decorator that wraps a training function with PRE/POST lifecycle.

    The decorated function's first positional argument (or the one at
    `config_path_arg` index) is used to locate the project root.

    Args:
        config_path_arg: Index of the positional arg that is the config path.
                         Defaults to 0 (first argument).
        capture_checkpoints: If True, creates a LineageCheckpointCallback and
                             injects it as `lineage_callback` kwarg into the
                             wrapped function.

    Returns:
        Decorator function.

    Example:
        @lineage_tracker(capture_checkpoints=True)
        def train(config_path: str, lineage_callback=None):
            trainer = Trainer(..., callbacks=[lineage_callback])
            trainer.train()
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Resolve config_path from args
            cp = kwargs.get("config_path") or (
                args[config_path_arg] if len(args) > config_path_arg else None
            )

            client = LineageClient(config_path=cp)
            ctx = client.pre_execution()

            if ctx is None:
                # Non-blocking mode, server unreachable — run without tracking
                return fn(*args, **kwargs)

            # Inject checkpoint callback if requested
            if capture_checkpoints:
                callback = LineageCheckpointCallback(ctx=ctx)
                kwargs["lineage_callback"] = callback

            try:
                result = fn(*args, **kwargs)
                client.post_execution(ctx, status="COMPLETED")
                return result
            except Exception as e:
                client.post_execution(ctx, status="FAILED", exit_message=str(e))
                raise
            finally:
                client.close()

        return wrapper

    return decorator
