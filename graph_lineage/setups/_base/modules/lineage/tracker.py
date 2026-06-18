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
from .client import LineageClient

logger = logging.getLogger(__name__)



def LineageCheckpointCallback(*args, **kwargs):
    """Lazy accessor — avoids importing transformers at module load time."""
    from .callbacks import LineageCheckpointCallback as _Cls
    return _Cls(*args, **kwargs)

def _extract_metrics_uri_from_config(config_path: str, experiment_id: str) -> str | None:
    """Extract metrics_uri from config.yml, resolving ${experiment.id}."""
    import yaml
    from pathlib import Path

    config_file = Path(config_path)
    if not config_file.exists():
        return None

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return None

    metrics_uri = config.get("output", {}).get("metrics_uri")
    if metrics_uri and "${experiment.id}" in metrics_uri:
        metrics_uri = metrics_uri.replace("${experiment.id}", experiment_id)
    return metrics_uri


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
            # 1. Resolve config_path
            cp = kwargs.get("config_path") or (
                args[config_path_arg] if len(args) > config_path_arg else None
            )

            # 2. Initialize client
            client = LineageClient(config_path=cp)
            ctx = client.pre_execution()

            # 3. Non-blocking mode: server unreachable
            if ctx is None:
                logger.warning("Lineage server unreachable, running without tracking")
                return fn(*args, **kwargs)

            # 4. Inject checkpoint callback if requested
            if capture_checkpoints:
                # Import the callback (lazy to avoid circular imports)
                from .callbacks import LineageCheckpointCallback
                callback = LineageCheckpointCallback(ctx=ctx)
                kwargs["lineage_callback"] = callback

            result = None
            metrics_uri = None

            try:
                # 5. Execute training
                result = fn(*args, **kwargs)

                # 6. Extract metrics_uri from result (if dict)
                if isinstance(result, dict) and "metrics_uri" in result:
                    metrics_uri = result["metrics_uri"]

                # 7. Fallback: extract from config.yml
                if metrics_uri is None and cp:
                    metrics_uri = _extract_metrics_uri_from_config(cp, ctx.experiment_id)

                # 8. POST-execution (success)
                client.post_execution(
                    ctx=ctx,
                    status="COMPLETED",
                    metrics_uri=metrics_uri,
                )
                return result

            except Exception as e:
                # 9. Extract metrics_uri from config even on failure
                if metrics_uri is None and cp:
                    try:
                        metrics_uri = _extract_metrics_uri_from_config(cp, ctx.experiment_id)
                    except Exception:
                        pass

                # 10. POST-execution (failure)
                client.post_execution(
                    ctx=ctx,
                    status="FAILED",
                    exit_message=str(e),
                    metrics_uri=metrics_uri,
                )
                raise

            finally:
                client.close()

        return wrapper

    return decorator
