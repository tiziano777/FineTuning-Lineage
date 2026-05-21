"""Tracker decorator: @envelope.tracker() wraps training functions with PRE/POST lifecycle."""

from __future__ import annotations

import functools
import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.config_file.validator import validate_pre_execution
from graph_lineage.config_file.writer import save_config
from graph_lineage.diff.snapshot import CodebaseSnapshot, capture_snapshot
from graph_lineage.lineage.neo4j_ops import (
    create_edge,
    create_experiment_node,
    find_parent_experiment,
    update_experiment_status,
)
from graph_lineage.lineage.rule_engine import detect_run_type
from graph_lineage.observability.collector import MetricsCollector, set_collector
from graph_lineage.storage.local_provider import LocalStorageProvider

logger = logging.getLogger(__name__)

# Edge type mapping per strategy
_STRATEGY_EDGE_MAP: dict[str, str] = {
    "BRANCH": "DERIVED_FROM",
    "RETRY": "RETRY_OF",
    "RESUME": "STARTED_FROM",
    "MERGE": "DERIVED_FROM",
}


@dataclass
class ExecutionContext:
    """State passed from PRE to POST execution."""

    exp_id: str
    strategy: str
    config: LineageConfig
    config_path: str
    extra: dict[str, Any] = field(default_factory=dict)
    collector: MetricsCollector | None = field(default=None, repr=False)


def _pre_execution(
    args: tuple,
    kwargs: dict,
    blocking: bool,
    collect_every: int = 100,
) -> ExecutionContext | None:
    """PRE-execution phase: validate config, detect run type, create experiment.

    Args:
        args: Positional args from decorated function (first = config_path).
        kwargs: Keyword args from decorated function.
        blocking: If True, errors cause sys.exit; if False, return None.

    Returns:
        ExecutionContext on success, None on non-blocking failure.
    """
    try:
        # 1. Extract config_path
        config_path = kwargs.get("config_path") or (args[0] if args else None)
        if not config_path:
            raise ValueError("config_path must be the first argument or keyword arg")
        config_path = str(config_path)

        # 2. Load YAML → LineageConfig
        with open(config_path) as f:
            data = yaml.safe_load(f)
        config = LineageConfig.model_validate(data)

        # 3. Resolve StorageProvider (local)
        storage = LocalStorageProvider()

        # 4. validate_pre_execution
        errors = validate_pre_execution(config, storage)
        if errors:
            msg = "; ".join(f"{e.field}: {e.message}" for e in errors)
            logger.error("Validation failed: %s", msg)
            if blocking:
                sys.exit(errors[0].exit_code)
            return None

        # 5. Capture codebase snapshot
        project_root = Path(config_path).resolve().parent
        snapshot = capture_snapshot(project_root)

        # 6. Query Neo4j for parent experiment
        parent = find_parent_experiment(config.experiment.uri)

        # 7. Detect run type
        run_result = detect_run_type(config, snapshot, parent)

        # 8. Build Experiment node
        exp_id = str(uuid.uuid4())
        hashes = snapshot.hashes()
        is_base = run_result.strategy == "NEW"

        from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment

        experiment = Experiment(
            id=exp_id,
            description=config.experiment.description,
            uri=config.experiment.uri,
            base=is_base,
            status="RUNNING",
            strategy=run_result.strategy,
            codebase=snapshot.files if is_base else (run_result.diff_patch or {}),
            config_hash=hashes.get("config.yaml", ""),
            prepare_hash=hashes.get("prepare.py", ""),
            train_hash=hashes.get("train.py", ""),
            requirements_hash=hashes.get("requirements.txt", ""),
        )

        # 9. Create node in Neo4j
        create_experiment_node(experiment)

        # 10. Create edges based on strategy
        if run_result.parent_exp_id and run_result.strategy in _STRATEGY_EDGE_MAP:
            edge_type = _STRATEGY_EDGE_MAP[run_result.strategy]
            edge_props: dict[str, Any] = {}
            if run_result.diff_patch:
                edge_props["diff_patch"] = str(run_result.diff_patch)
            create_edge(exp_id, run_result.parent_exp_id, edge_type, edge_props or None)

        # 11. Write back experiment.id to config
        config.experiment.id = exp_id
        config.experiment.status = "RUNNING"
        save_config(config, config_path, storage)

        logger.info(
            "PRE-execution complete: strategy=%s, exp_id=%s",
            run_result.strategy,
            exp_id,
        )

        # 12. Instantiate MetricsCollector
        collector = MetricsCollector(
            experiment_id=exp_id,
            metrics_uri=config.output.metrics_uri,
            collect_every=collect_every,
        )
        set_collector(collector)

        return ExecutionContext(
            exp_id=exp_id,
            strategy=run_result.strategy,
            config=config,
            config_path=config_path,
            collector=collector,
        )

    except SystemExit:
        raise
    except Exception as exc:
        logger.error("PRE-execution error: %s", exc, exc_info=True)
        if blocking:
            sys.exit(4)
        return None


def _post_execution(
    ctx: ExecutionContext,
    status: str,
    exit_msg: str | None = None,
) -> None:
    """POST-execution phase: update experiment status in Neo4j.

    Args:
        ctx: ExecutionContext from PRE phase.
        status: Final status (COMPLETED or FAILED).
        exit_msg: Optional error message on failure.
    """
    try:
        # Finalize collector (flush remaining metrics)
        if ctx.collector:
            ctx.collector.finalize()

        update_experiment_status(ctx.exp_id, status, exit_msg)

        # Update config status
        ctx.config.experiment.status = status
        storage = LocalStorageProvider()
        save_config(ctx.config, ctx.config_path, storage)

        logger.info("POST-execution complete: status=%s, exp_id=%s", status, ctx.exp_id)
    except Exception as exc:
        logger.error("POST-execution error: %s", exc, exc_info=True)


class envelope:
    """Namespace for lineage tracking decorators."""

    @staticmethod
    def tracker(blocking: bool = True, collect_every: int = 100) -> Callable:
        """Decorator that wraps a training function with PRE/POST lifecycle.

        Args:
            blocking: If True (default), PRE failures cause sys.exit.
                      If False, PRE failures are logged and function runs anyway.
            collect_every: Flush metrics every N steps (default 100).

        Returns:
            Decorator function.
        """

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                ctx = _pre_execution(args, kwargs, blocking, collect_every)
                if ctx is None:
                    # Non-blocking mode, PRE failed
                    return fn(*args, **kwargs)
                try:
                    result = fn(*args, **kwargs)
                    _post_execution(ctx, status="COMPLETED")
                    return result
                except Exception as e:
                    _post_execution(ctx, status="FAILED", exit_msg=str(e))
                    raise

            return wrapper

        return decorator
