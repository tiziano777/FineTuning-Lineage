"""Lineage Client SDK — easy-to-integrate tracking for training scripts.

Public API:
    - LineageClient: Full client for manual PRE/POST lifecycle
    - lineage_tracker: Decorator that wraps training functions automatically
    - ServerConfig, ServerConfigError: Configuration classes
    - Connector, ConnectorFactory, ServerError: Transport layer
    - PreRequest, PreResponse, PostRequest, PostResponse: Payloads

Usage as decorator:
    from modules.lineage import lineage_tracker

    @lineage_tracker(blocking=False)
    def train(config_path: str, lineage_emit=None):
        # ... training logic ...
        lineage_emit("Metric", {"name": "loss", "value": 0.123})
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
import os
import yaml
from typing import Any, Callable, Dict, Optional

from .http.client import LineageClient

logger = logging.getLogger(__name__)

def _get_merged_config(config_path: str) -> Dict[str, Any]:
    """Legge config_path e .lineage/experiment.yml, esegue il deep merge

    e restituisce il dizionario unito SENZA modificare i file su disco.
    """
    lineage_path = os.path.join(".lineage", "experiment.yml")

    # 1. Carica la configurazione del progetto (Base)
    config_data = {}
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Errore durante la lettura di {config_path}: {e}")
    else:
        logger.warning(f"File di configurazione non trovato in: {config_path}. Uso dizionario vuoto.")

    # 2. Funzione interna di Deep Merge
    def deep_merge(dict1: dict, dict2: dict):
        for key, value in dict2.items():
            if isinstance(value, dict) and key in dict1 and isinstance(dict1[key], dict):
                deep_merge(dict1[key], value)
            else:
                dict1[key] = value

    # 3. Carica il lineage globale (.lineage/experiment.yml)
    if not config_data.get("experiment"):
        lineage_data = {}
        if os.path.exists(lineage_path):
            try:
                with open(lineage_path, 'r') as f:
                    lineage_data = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"Impossibile leggere il file lineage {lineage_path}: {e}")

        deep_merge(config_data, lineage_data)

    return config_data

def _update_local_base_state(config_path: Optional[str], response: Any) -> None:
    """Aggiorna .lineage/experiment.yml con il nuovo stato base dopo un model switch.

    Il server, in caso di model switch non-blocking, restituisce un nuovo base_experiment_id
    che deve essere persistito localmente per mantenere la coerenza della chain.
    """
    lineage_path = os.path.join(".lineage", "experiment.yml")
    os.makedirs(".lineage", exist_ok=True)

    state: Dict[str, Any] = {}
    if os.path.exists(lineage_path):
        try:
            with open(lineage_path, 'r') as f:
                state = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Impossibile leggere %s: %s", lineage_path, e)

    # Aggiorna solo se la response contiene i campi di un model switch
    exp_id = getattr(response, 'experiment_id', None)
    base_exp_id = getattr(response, 'base_experiment_id', None)
    prev_exp_id = getattr(response, 'previous_experiment_id', None)
    strategy = getattr(response, 'strategy', None)
    is_base = getattr(response, 'base', None)

    if exp_id:
        state["experiment_id"] = exp_id
    if base_exp_id:
        state["base_experiment_id"] = base_exp_id
    if prev_exp_id is not None:
        state["previous_experiment_id"] = prev_exp_id
    if strategy is not None:
        state["strategy"] = strategy
    if is_base is not None:
        state["base"] = is_base

    try:
        with open(lineage_path, 'w') as f:
            yaml.safe_dump(state, f, default_flow_style=False)
        logger.info("Stato base aggiornato in %s (exp_id=%s, base=%s)",
                    lineage_path, exp_id, is_base)
    except Exception as e:
        logger.warning("Fallito aggiornamento stato locale: %s", e)

def _extract_metrics_uri_from_config(config_path: str, experiment_id: str) -> str | None:
    """Extract metrics_uri from config.yml, resolving ${experiment.id}."""
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

def lineage_tracker(
    config_path_arg: int = 0,
    blocking: bool = False, 
) -> Callable:
    """Decorator that wraps a training function with PRE/POST lifecycle.

    The decorated function's first positional argument (or the one at
    `config_path_arg` index) is used to locate the project root AND to
    read an optional 'experiment' block that overrides .lineage/experiment.yml.
    This supports orchestration scenarios where experiment metadata is injected
    per-run directly into the training config.

    The wrapped function is expected to return None or 0 on success. If it
    returns None, the decorator normalises the exit value to 0 so callers
    can rely on a consistent integer return code.

    Args:
        config_path_arg: Index of the positional arg that is the config path.
                         Defaults to 0 (first argument).
        blocking: If True, a model mismatch against the parent chain
                  raises a blocking error. If False, the server handles the switch
                  by creating a new base experiment.

    Returns:
        Decorator function.

    Example:
        @lineage_tracker(blocking=False)
        def train(config_path: str, lineage_emit=None):
            # training logic
            lineage_emit("Metric", {"name": "accuracy", "value": 0.95})
            # no explicit return needed — decorator normalises to 0
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 1. Resolve config_path
            cp = kwargs.get("config_path") or (
                args[config_path_arg] if len(args) > config_path_arg else None
            )
            # --- FASE DEEP MERGE ---
            if cp:
                logger.info("Esecuzione della fase di Deep Merge per il file: %s", cp)
                merged_config = _get_merged_config(cp)
            else:
                logger.warning("Nessun config_path rilevato. Fase di Deep Merge saltata.")
                merged_config = {}
            # ---------------------------------------------------

            logger.info("Configurazione Experiment dopo Deep Merge: %s", str(merged_config.get('experiment', {})))

            # 2. Initialize client
            client = LineageClient(
                config_dict=merged_config,
                config_path=cp,
                blocking=blocking,
            )

            logger.info("Lineage client initialized with config_path: %s, project_root: %s, blocking: %s",
                        client._config_path, client._project_root, blocking)

            # 3. PRE-execution: send metadata to server and get context
            ctx = client.pre_execution()

            # Se il server ha triggerato un model switch, aggiorna stato locale
            if ctx is not None and getattr(ctx, 'base', False) and getattr(ctx, 'base_experiment_id', None):
                _update_local_base_state(cp, ctx)

            # 4. Non-blocking mode: server unreachable — run without tracking
            if ctx is None:
                logger.warning("Lineage server unreachable, running without tracking")
                result = fn(*args, **kwargs)
                return 0 if result is None else result

            # 5. Prepare emit function (always injected as lineage_emit)
            def emit(node_type: str, payload: dict[str, Any], edge_type: str = "produced") -> None:
                client.emit_node(ctx, node_type, payload, edge_type)

            kwargs["lineage_emit"] = emit

            result = None
            metrics_uri = None

            try:
                # 6. Execute training
                result = fn(*args, **kwargs)

                # 7. Extract metrics_uri from result (if dict),
                #  then store to Postgres
                if isinstance(result, dict) and "metrics_uri" in result:
                    metrics_uri = result["metrics_uri"]

                # 8. Fallback: extract from config.yml
                if metrics_uri is None and cp:
                    metrics_uri = _extract_metrics_uri_from_config(cp, ctx.experiment_id)

                # 9. POST-execution (success)
                client.post_execution(
                    ctx=ctx,
                    status="COMPLETED",
                    metrics_uri=metrics_uri,
                )

                # 10. Normalise return: training functions typically return None;
                #    return 0 as a clean success exit code for callers that check it.
                return 0 if result is None else result

            except Exception as e:
                # 11. Extract metrics_uri from config even on failure
                if metrics_uri is None and cp:
                    try:
                        metrics_uri = _extract_metrics_uri_from_config(cp, ctx.experiment_id)
                    except Exception:
                        pass

                # 12. POST-execution (failure)
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