"""Pre-execution validation for LineageConfig.

Runs environmental and logical checks before the training hook proceeds.
Returns a list of ValidationError instances; empty list = all checks passed.
"""

from __future__ import annotations

from dataclasses import dataclass

from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.storage.provider import StorageProvider

VALID_MERGE_METHODS = {"linear", "slerp", "ties", "dare", "task_arithmetic"}


@dataclass(frozen=True)
class ValidationError:
    """A single validation failure."""

    field: str
    message: str
    exit_code: int


def validate_pre_execution(
    config: LineageConfig,
    storage: StorageProvider,
    previous_recipe_snapshot: dict | None = None,
) -> list[ValidationError]:
    """Run all pre-execution checks against the config.

    Args:
        config: Parsed LineageConfig instance.
        storage: StorageProvider for filesystem checks.
        previous_recipe_snapshot: Recipe entries from previous run (for guard check).

    Returns:
        List of ValidationError. Empty means all checks passed.
    """
    errors: list[ValidationError] = []

    # 1. experiment.uri exists and is directory
    if not storage.exists(config.experiment.uri) or not storage.is_dir(config.experiment.uri):
        errors.append(ValidationError(
            field="experiment.uri",
            message=f"Path does not exist or is not a directory: {config.experiment.uri}",
            exit_code=2,
        ))

    # 2. output.output_dir is writable
    try:
        writable = storage.is_writable(config.output.output_dir)
    except PermissionError:
        writable = False
    if not writable:
        errors.append(ValidationError(
            field="output.output_dir",
            message=f"Output directory is not writable: {config.output.output_dir}",
            exit_code=3,
        ))

    # 3. model["model_name"] non-empty
    model_name = config.model.get("model_name", "")
    if not model_name or not str(model_name).strip():
        errors.append(ValidationError(
            field="model.model_name",
            message="model.model_name is required and must be non-empty",
            exit_code=2,
        ))

    # 4. model["framework"] non-empty
    framework = config.model.get("framework", "")
    if not framework or not str(framework).strip():
        errors.append(ValidationError(
            field="model.framework",
            message="model.framework is required and must be non-empty",
            exit_code=2,
        ))

    # 5. experiment.name non-empty (already enforced by Pydantic, but double-check)
    if not config.experiment.name or not config.experiment.name.strip():
        errors.append(ValidationError(
            field="experiment.name",
            message="experiment.name is required and must be non-empty",
            exit_code=2,
        ))

    # 6. checkpoint_resume_from → URI resolvable
    if config.experiment.checkpoint_resume_from:
        ckp_ref = config.experiment.checkpoint_resume_from
        if not storage.exists(ckp_ref):
            errors.append(ValidationError(
                field="experiment.checkpoint_resume_from",
                message=f"Checkpoint reference not resolvable: {ckp_ref}",
                exit_code=3,
            ))

    # 7. model_merging.enabled → sources >= 2
    if config.model_merging.enabled and len(config.model_merging.sources) < 2:
        errors.append(ValidationError(
            field="model_merging.sources",
            message="Model merging requires at least 2 sources",
            exit_code=2,
        ))

    # 8. model_merging.enabled → merge_method valid
    if config.model_merging.enabled:
        if config.model_merging.merge_method not in VALID_MERGE_METHODS:
            errors.append(ValidationError(
                field="model_merging.merge_method",
                message=f"Invalid merge method: {config.model_merging.merge_method}. "
                        f"Valid: {sorted(VALID_MERGE_METHODS)}",
                exit_code=2,
            ))

    # 9. Conflict: checkpoint_resume_from AND model_merging.enabled
    if config.experiment.checkpoint_resume_from and config.model_merging.enabled:
        errors.append(ValidationError(
            field="experiment.checkpoint_resume_from + model_merging.enabled",
            message="Cannot have both checkpoint_resume_from and model_merging enabled",
            exit_code=5,
        ))

    # 10. Recipe guard: entries must match previous snapshot
    if previous_recipe_snapshot is not None:
        if config.recipe.entries != previous_recipe_snapshot:
            errors.append(ValidationError(
                field="recipe.entries",
                message="Recipe entries changed since last run. "
                        "Update recipe via UI before re-running.",
                exit_code=5,
            ))

    return errors
