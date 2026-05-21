"""Atomic config.yml loader and writer.

Uses StorageProvider for all I/O. Write-back is atomic:
backup original → write temp → rename temp to target.
"""

from __future__ import annotations

import os

import yaml

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.storage.provider import StorageProvider

_MANAGED_HEADER = """\
# ============================================================
# LINEAGE-MANAGED — Do not edit fields below manually
# ============================================================
"""

_USER_HEADER = """\
# ============================================================
# USER-DEFINED — Edit freely
# ============================================================
"""


def load_config(path: str, storage: StorageProvider) -> LineageConfig:
    """Load and parse config.yml into a LineageConfig instance.

    Args:
        path: Path to config.yml (relative or absolute, resolved by storage).
        storage: StorageProvider for reading.

    Returns:
        Parsed LineageConfig.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If YAML is malformed or validation fails.
    """
    content = storage.read_text(path)
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValueError(f"config.yml must be a YAML mapping, got: {type(data).__name__}")
    return LineageConfig.model_validate(data)


def save_config(config: LineageConfig, path: str, storage: StorageProvider) -> None:
    """Atomically write config back to YAML with zone comments.

    Pattern:
    1. Backup original (if exists)
    2. Serialize to YAML with zone comments
    3. Write to temp file
    4. Rename temp → target (atomic on POSIX)

    Args:
        config: LineageConfig to serialize.
        path: Target path for config.yml.
        storage: StorageProvider for I/O.
    """
    # 1. Backup original
    if storage.exists(path):
        storage.backup(path)

    # 2. Serialize
    data = config.model_dump(mode="python")
    yaml_content = _serialize_with_comments(data)

    # 3. Write to temp, then rename
    tmp_path = path + ".tmp"
    storage.write_text(tmp_path, yaml_content)

    # 4. Atomic rename (POSIX guarantees atomicity for same-filesystem rename)
    os.rename(tmp_path, path)


def _serialize_with_comments(data: dict) -> str:
    """Serialize config dict to YAML string with zone separator comments."""
    managed_keys = ["experiment"]
    user_keys = ["model", "recipe", "output", "hardware", "model_merging"]

    lines: list[str] = []

    # Managed section
    lines.append(_MANAGED_HEADER)
    managed_data = {k: data[k] for k in managed_keys if k in data}
    if managed_data:
        lines.append(yaml.dump(managed_data, default_flow_style=False, sort_keys=False, allow_unicode=True))

    # User section
    lines.append(_USER_HEADER)
    user_data = {k: data[k] for k in user_keys if k in data}
    if user_data:
        lines.append(yaml.dump(user_data, default_flow_style=False, sort_keys=False, allow_unicode=True))

    return "\n".join(lines)
