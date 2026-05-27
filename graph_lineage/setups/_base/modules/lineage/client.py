"""LineageClient: main entry point for client-server lineage communication.

Handles the PRE/POST lifecycle by capturing local state and communicating
with the lineage server via a connector.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import ServerConfig, ServerConfigError, load_server_config
from .connector import Connector, ConnectorFactory, ServerError
from .models import PostRequest, PreRequest, PreResponse
from .snapshot import FileTooLargeError, capture_codebase

logger = logging.getLogger(__name__)


class LineageClientError(Exception):
    """Raised on unrecoverable client errors."""


@dataclass
class ExecutionContext:
    """State passed from PRE to POST execution within a single run."""

    experiment_id: str
    strategy: str
    project_root: Path
    server_config: ServerConfig
    extra: dict[str, Any] = field(default_factory=dict)


def _find_project_root(start: Path) -> Path:
    """Walk up from start to find directory containing .lineage/.

    Args:
        start: Starting directory to search from.

    Returns:
        Path to project root.

    Raises:
        LineageClientError: If no .lineage/ directory found.
    """
    current = start.resolve()
    while current != current.parent:
        if (current / ".lineage").is_dir():
            return current
        current = current.parent
    raise LineageClientError(
        f"No .lineage/ directory found walking up from '{start}'. "
        f"Ensure .lineage/server.yml and .lineage/experiment.yml exist."
    )


def _load_experiment_yml(project_root: Path) -> dict[str, Any]:
    """Load .lineage/experiment.yml and return the experiment dict."""
    exp_path = project_root / ".lineage" / "experiment.yml"
    if not exp_path.exists():
        raise LineageClientError(f"Missing '{exp_path}'")
    with open(exp_path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("experiment", {})


def _save_experiment_yml(project_root: Path, experiment_data: dict[str, Any]) -> None:
    """Save updated experiment data back to .lineage/experiment.yml."""
    exp_path = project_root / ".lineage" / "experiment.yml"
    with open(exp_path, "w") as f:
        yaml.dump({"experiment": experiment_data}, f, default_flow_style=False, sort_keys=False)


class LineageClient:
    """Client for lineage tracking communication with the server.

    Manages the full PRE/POST lifecycle:
    1. PRE: Capture codebase → send to server → receive strategy/exp_id
    2. POST: Send final status to server

    Usage:
        client = LineageClient(project_root=Path("."))
        ctx = client.pre_execution()
        # ... run training ...
        client.post_execution(ctx, status="COMPLETED")
    """

    def __init__(self, project_root: Path | None = None, config_path: str | None = None):
        """Initialize the client.

        Args:
            project_root: Explicit project root path. If None, auto-detected
                          from config_path or current directory.
            config_path: Path to config.yml (used for auto-detecting project root).
        """
        if project_root is not None:
            self._project_root = project_root.resolve()
        elif config_path is not None:
            self._project_root = _find_project_root(Path(config_path).resolve().parent)
        else:
            self._project_root = _find_project_root(Path.cwd())

        self._server_config: ServerConfig | None = None
        self._connector: Connector | None = None

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def server_config(self) -> ServerConfig:
        if self._server_config is None:
            self._server_config = load_server_config(self._project_root)
        return self._server_config

    def _get_connector(self) -> Connector:
        """Get or create the connector instance."""
        if self._connector is None:
            self._connector = ConnectorFactory.create(self.server_config)
        return self._connector

    def _retry(self, fn, retries: int | None = None):
        """Execute fn with retries on ConnectionError."""
        max_retries = retries if retries is not None else self.server_config.retries
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except ConnectionError as e:
                last_error = e
                if attempt < max_retries:
                    wait = 2 ** attempt  # exponential backoff: 1, 2, 4s
                    logger.warning(
                        "Connection failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, max_retries + 1, wait, e,
                    )
                    time.sleep(wait)
        raise last_error  # type: ignore[misc]

    def pre_execution(self) -> ExecutionContext | None:
        """Execute PRE phase: capture codebase, send to server, update local state.

        Returns:
            ExecutionContext on success.
            None if non-blocking mode and communication failed.

        Raises:
            SystemExit: If blocking mode and communication fails.
        """
        blocking = self.server_config.blocking

        try:
            # 1. Load experiment config
            exp_data = _load_experiment_yml(self._project_root)

            # 2. Capture codebase snapshot
            codebase = capture_codebase(self._project_root)

            # 3. Build PRE request
            request = PreRequest(
                experiment_name=exp_data.get("name", ""),
                experiment_uri=exp_data.get("uri") or str(self._project_root),
                base_experiment_id=exp_data.get("base_experiment_id"),
                previous_experiment_id=exp_data.get("id"),  # current id becomes previous
                description=exp_data.get("description"),
                model_uri=exp_data.get("model_uri", ""),
                model_id=exp_data.get("model_id", ""),
                codebase=codebase,
                checkpoint_resume_from=exp_data.get("checkpoint_resume_from"),
            )

            # 4. Send to server (with retries)
            connector = self._get_connector()
            response: PreResponse = self._retry(lambda: connector.send_pre(request))

            # 5. Update local .lineage/experiment.yml
            exp_data["id"] = response.experiment_id
            exp_data["previous_experiment_id"] = request.previous_experiment_id
            exp_data["base_experiment_id"] = response.base_experiment_id
            exp_data["base"] = response.base
            exp_data["status"] = "RUNNING"
            exp_data["uri"] = request.experiment_uri
            _save_experiment_yml(self._project_root, exp_data)

            logger.info(
                "PRE-execution complete: strategy=%s, exp_id=%s",
                response.strategy, response.experiment_id,
            )

            return ExecutionContext(
                experiment_id=response.experiment_id,
                strategy=response.strategy,
                project_root=self._project_root,
                server_config=self.server_config,
            )

        except FileTooLargeError as e:
            logger.error("BLOCKED: %s", e)
            sys.exit(8)

        except ServerError as e:
            logger.error("Server rejected PRE request: %s", e)
            if blocking:
                sys.exit(9)
            return None

        except (ConnectionError, ServerConfigError) as e:
            logger.error("PRE-execution communication failed: %s", e)
            if blocking:
                sys.exit(10)
            return None

        except Exception as e:
            logger.error("PRE-execution error: %s", e, exc_info=True)
            if blocking:
                sys.exit(4)
            return None

    def post_execution(
        self,
        ctx: ExecutionContext,
        status: str,
        exit_message: str | None = None,
        metrics_uri: str | None = None,
    ) -> None:
        """Execute POST phase: report final status to server.

        Args:
            ctx: ExecutionContext from pre_execution.
            status: "COMPLETED" or "FAILED".
            exit_message: Optional error message on failure.
            metrics_uri: Optional URI where metrics logs are stored.
        """
        try:
            request = PostRequest(
                experiment_id=ctx.experiment_id,
                status=status,
                exit_message=exit_message,
                metrics_uri=metrics_uri,
            )

            connector = self._get_connector()
            self._retry(lambda: connector.send_post(request))

            # Update local state
            exp_data = _load_experiment_yml(self._project_root)
            exp_data["status"] = status
            _save_experiment_yml(self._project_root, exp_data)

            logger.info("POST-execution complete: status=%s, exp_id=%s", status, ctx.experiment_id)

        except Exception as e:
            logger.error("POST-execution error: %s", e, exc_info=True)

    def close(self) -> None:
        """Release resources."""
        if self._connector is not None:
            self._connector.close()
            self._connector = None
