"""Root LineageConfig — composes experiment metadata + training config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.config_file.data_classes.model_merging_config import ModelMergingConfig
from graph_lineage.config_file.data_classes.output_config import OutputConfig
from graph_lineage.config_file.data_classes.recipe_config import RecipeConfig


def _find_project_root(start: Path) -> Path:
    """Walk up from start to find project root.

    Marker priority: .lineage/ > .git > pyproject.toml.
    Raises FileNotFoundError if no marker found (prevents silent wrong-dir capture).
    """
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".lineage").is_dir():
            return parent
    # Fallback to .git or pyproject.toml
    for parent in [current, *current.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError(
        f"Cannot find project root from {start}. "
        "Expected .lineage/, .git, or pyproject.toml in a parent directory. "
        "Run from your project root or create a .lineage/ directory."
    )


class LineageConfig(BaseModel):
    """Root config — strict on experiment/recipe, flexible on model/hardware.

    Composes ExperimentConfig (from .lineage/experiment.yml) with
    TrainingConfig fields (from config.yml).
    """

    experiment: ExperimentConfig
    model: dict[str, Any] = Field(default_factory=dict)
    recipe: RecipeConfig = Field(default_factory=RecipeConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    hardware: dict[str, Any]  = Field(default_factory=dict)
    model_merging: ModelMergingConfig = Field(default_factory=ModelMergingConfig)

    @model_validator(mode="after")
    def _validate_model_minimum_keys(self) -> "LineageConfig":
        """Enforce minimum required keys in the flexible model dict."""
        model_uri = self.model.get("model_uri")
        if not model_uri or not isinstance(model_uri, str) or not model_uri.strip():
            raise ValueError("model.model_uri is required and must be non-empty")

        model_id = self.model.get("model_id")
        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("model.model_id is required and must be non-empty")

        return self

    @classmethod
    def from_files(cls, config_path: str | Path) -> "LineageConfig":
        """Load LineageConfig from split files: config.yml + .lineage/experiment.yml.

        Args:
            config_path: Path to the training config.yml file.

        Returns:
            Composed LineageConfig from both sources.

        Raises:
            FileNotFoundError: If .lineage/experiment.yml is missing (no fallback).
            ValueError: If YAML is malformed or validation fails.
        """
        config_path = Path(config_path).resolve()
        project_root = _find_project_root(config_path.parent)
        lineage_file = project_root / ".lineage" / "experiment.yml"

        # Load experiment config from .lineage/experiment.yml
        if not lineage_file.exists():
            # Fallback: try reading experiment from config.yml itself (legacy mode)
            with open(config_path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ValueError(f"config.yml must be a YAML mapping, got: {type(data).__name__}")
            return cls.model_validate(data)

        # New split mode: read both files
        with open(lineage_file) as f:
            experiment_data = yaml.safe_load(f)
        if not isinstance(experiment_data, dict):
            raise ValueError(f".lineage/experiment.yml must be a YAML mapping, got: {type(experiment_data).__name__}")

        with open(config_path) as f:
            training_data = yaml.safe_load(f)
        if not isinstance(training_data, dict):
            raise ValueError(f"config.yml must be a YAML mapping, got: {type(training_data).__name__}")

        # Compose: experiment from .lineage, everything else from config.yml
        combined = {**training_data, "experiment": experiment_data.get("experiment", experiment_data)}
        return cls.model_validate(combined)
