"""Root LineageConfig — composes all sub-configs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.config_file.data_classes.model_merging_config import ModelMergingConfig
from graph_lineage.config_file.data_classes.output_config import OutputConfig
from graph_lineage.config_file.data_classes.recipe_config import RecipeConfig


class LineageConfig(BaseModel):
    """Root config — strict on experiment/recipe, flexible on model/hardware."""

    experiment: ExperimentConfig
    model: dict[str, Any] = Field(default_factory=dict)
    recipe: RecipeConfig = Field(default_factory=RecipeConfig)
    output: OutputConfig
    hardware: dict[str, Any] = Field(default_factory=dict)
    model_merging: ModelMergingConfig = Field(default_factory=ModelMergingConfig)

    @model_validator(mode="after")
    def _validate_model_minimum_keys(self) -> "LineageConfig":
        """Enforce minimum required keys in the flexible model dict."""
        model_name = self.model.get("model_name")
        if not model_name or not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model.model_name is required and must be non-empty")

        framework = self.model.get("framework")
        if not framework or not isinstance(framework, str) or not framework.strip():
            raise ValueError("model.framework is required and must be non-empty")

        return self
