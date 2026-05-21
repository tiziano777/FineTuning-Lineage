"""Pydantic models for Experiment entity."""

from __future__ import annotations

from typing import Optional
from pydantic import Field
from .base import BaseEntity


class Experiment(BaseEntity):
    """Experiment entity -- core tracking entity for a training run."""

    description: Optional[str] = Field("", description="Experiment description")
    uri: str = Field("", description="Path scaffold on worker")
    base: bool = Field(True, description="True for base experiment, False for derived")

    status: Optional[str] = Field("RUNNING", description="RUNNING | COMPLETED | FAILED | PAUSED")
    exit_status: Optional[str] = None
    exit_msg: Optional[str] = None
    strategy: str = Field("", description="NEW | RESUME | BRANCH | RETRY")

    codebase: dict = Field(default_factory=dict, description="base=True: full snapshot dict[str, str]; base=False: unified diff dict")
    config_hash: str = Field("", description="SHA-256 of config.yaml")
    prepare_hash: str = Field("", description="SHA-256 of prepare.py")
    train_hash: str = Field("", description="SHA-256 of train.py")
    requirements_hash: str = Field("", description="SHA-256 of requirements.txt")

    usable: bool = Field(True, description="Is experiment usable")
    manual_save: bool = Field(False, description="Manually saved")

    metrics_uri: str = Field("", description="Pointer to training metrics")
    hw_metrics_uri: str = Field("", description="Pointer to hardware metrics")
