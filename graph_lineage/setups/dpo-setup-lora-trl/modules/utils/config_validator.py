"""config_validator.py — Config loader with variable interpolation and strict validation."""

from __future__ import annotations

import logging
import os
import re
import traceback

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """Load and validate a YAML config file. Raises on any failure."""
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("Config file not found: %s\n%s", config_path, traceback.format_exc())
        raise
    except yaml.YAMLError:
        logger.error("Invalid YAML in: %s\n%s", config_path, traceback.format_exc())
        raise

    if not isinstance(config, dict):
        raise ValueError(f"Config file is empty or not a mapping: {config_path}")

    return config


def require_field(config: dict, *keys: str, config_file: str = "config.yml"):
    """Extract a nested field from config. Raises ValueError if missing/None.

    Usage:
        model_id = require_field(config, "model", "model_id")
        batch_size = require_field(config, "model", "training", "per_device_train_batch_size")
    """
    path = ".".join(keys)
    current = config

    try:
        for key in keys:
            if not isinstance(current, dict):
                raise TypeError(
                    f"Expected dict at '{path}', got {type(current).__name__}"
                )
            if key not in current:
                raise KeyError(f"Key '{key}' not found")
            current = current[key]
    except (KeyError, TypeError) as e:
        msg = (
            f"CONFIG ERROR [{config_file}] -> {path}\n"
            f"  Error: {e}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        logger.error(msg)
        raise ValueError(msg) from e

    if current is None:
        msg = (
            f"CONFIG ERROR [{config_file}] -> {path}\n"
            f"  Field is None (empty). A value is required.\n"
        )
        logger.error(msg)
        raise ValueError(msg)

    return current


# ---------------------------------------------------------------------------
# Variable interpolation & directory creation
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# Path fields that should be created as directories after resolution
_DIR_FIELDS = [
    ("model", "dataset", "cache_dir"),
    ("output", "output_dir"),
    ("output", "metrics_uri"),
]


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict to dot-notation keys with scalar values."""
    result = {}
    for k, v in d.items():
        key = k if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            result.update(_flatten(v, key))
        elif isinstance(v, (str, int, float, bool)) and v is not None:
            result[key] = str(v)
    return result


def _interpolate(value: str, context: dict[str, str]) -> str:
    """Replace ${var.path} placeholders with values from context."""
    def replacer(match):
        var = match.group(1)
        if var not in context:
            raise ValueError(
                f"CONFIG ERROR: Variable '${{{var}}}' not found. "
                f"Available: {sorted(context.keys())}"
            )
        return context[var]
    return _VAR_PATTERN.sub(replacer, value)


def _walk_and_resolve(obj, context: dict[str, str]):
    """Recursively resolve all string values in a nested dict/list."""
    if isinstance(obj, dict):
        return {k: _walk_and_resolve(v, context) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_resolve(item, context) for item in obj]
    elif isinstance(obj, str) and "${" in obj:
        return _interpolate(obj, context)
    return obj


def resolve_config(config: dict) -> dict:
    """Resolve ${var} placeholders in all string values and create directory paths.

    Variables reference any scalar value in the config via dot-notation.
    Example: ${experiment.name} resolves to config["experiment"]["name"].
    """
    context = _flatten(config)
    resolved = _walk_and_resolve(config, context)

    # Create directories for known path fields
    for keys in _DIR_FIELDS:
        node = resolved
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                break
            node = node[k]
        else:
            if isinstance(node, str) and node:
                os.makedirs(node, exist_ok=True)
                logger.info("Ensured directory exists: %s", node)

    return resolved
