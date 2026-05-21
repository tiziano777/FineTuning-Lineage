"""YML message loader with user override support."""

from __future__ import annotations

from pathlib import Path

import yaml


_DEFAULT_PATH: Path = Path(__file__).parent / "lineage_messages.yml"


def load_messages(user_path: Path | None = None) -> dict:
    """Load message templates from YML file.

    If user_path is provided and exists, load from it.
    Otherwise, fall back to bundled default.
    """
    if user_path is not None and user_path.is_file():
        source = user_path
    else:
        source = _DEFAULT_PATH

    with open(source, encoding="utf-8") as f:
        return yaml.safe_load(f)
