"""Builder classes for creating test data.

Provides fluent API builders for constructing test fixtures:
- CodebaseSnapshotBuilder: Create file snapshots
- ExperimentBuilder: Create Experiment nodes
- CheckpointBuilder: Create Checkpoint nodes
- PreRequestBuilder: Create PreRequest payloads
- ConfigBuilder: Create LineageConfig instances
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Any

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.data_classes.neo4j.nodes.checkpoint import Checkpoint
from graph_lineage.diff.snapshot import CodebaseSnapshot
from graph_lineage.server.schemas import PreRequest
from graph_lineage.config_file.data_classes.lineage_config import LineageConfig
from graph_lineage.config_file.data_classes.experiment_config import ExperimentConfig
from graph_lineage.config_file.data_classes.output_config import OutputConfig
from graph_lineage.config_file.data_classes.model_merging_config import ModelMergingConfig


# ─────────────────────────────────────────────────────────────────────────────
# CodebaseSnapshotBuilder
# ─────────────────────────────────────────────────────────────────────────────


class CodebaseSnapshotBuilder:
    """Builder for creating CodebaseSnapshot instances."""

    def __init__(self):
        """Initialize with default files."""
        self._files: dict[str, str] = {
            "config.yaml": "model: llama",
            "prepare.py": "print('prep')",
            "train.py": "print('train')",
            "requirements.txt": "torch==2.0",
        }

    def with_train_script(self, code: str = "import torch") -> CodebaseSnapshotBuilder:
        """Set train.py content.

        Args:
            code: Python code for train.py

        Returns:
            Self for chaining
        """
        self._files["train.py"] = code
        return self

    def with_config(self, config_text: str) -> CodebaseSnapshotBuilder:
        """Set config.yaml content.

        Args:
            config_text: YAML configuration text

        Returns:
            Self for chaining
        """
        self._files["config.yaml"] = config_text
        return self

    def with_file(self, path: str, content: str) -> CodebaseSnapshotBuilder:
        """Add or update a file.

        Args:
            path: File path (e.g., "modules/utils.py")
            content: File content

        Returns:
            Self for chaining
        """
        self._files[path] = content
        return self

    def with_files(self, files: dict[str, str]) -> CodebaseSnapshotBuilder:
        """Replace all files.

        Args:
            files: Dict of path -> content

        Returns:
            Self for chaining
        """
        self._files = dict(files)
        return self

    def build(self) -> CodebaseSnapshot:
        """Build the snapshot.

        Returns:
            CodebaseSnapshot with configured files
        """
        return CodebaseSnapshot(files=dict(self._files))


# ─────────────────────────────────────────────────────────────────────────────
# ExperimentBuilder
# ─────────────────────────────────────────────────────────────────────────────


class ExperimentBuilder:
    """Builder for creating Experiment node instances."""

    def __init__(self):
        """Initialize with default values."""
        self._id = str(uuid4())
        self._uri = "/tmp/test-project"
        self._strategy = "NEW"
        self._base = True
        self._status = "RUNNING"
        self._description = "Test experiment"
        self._model_uri = "/nfs/llama-7b"
        self._model_id = "llama-7b-base"
        self._codebase: dict[str, str] = {
            "train.py": "import torch",
            "config.yaml": "model: llama",
        }
        self._changed_files: list[str] = []
        self._created_at = datetime.utcnow()
        self._updated_at = datetime.utcnow()

    def with_id(self, exp_id: str) -> ExperimentBuilder:
        """Set experiment ID.

        Args:
            exp_id: Experiment UUID

        Returns:
            Self for chaining
        """
        self._id = exp_id
        return self

    def with_uri(self, uri: str) -> ExperimentBuilder:
        """Set project URI.

        Args:
            uri: Project URI path

        Returns:
            Self for chaining
        """
        self._uri = uri
        return self

    def with_strategy(self, strategy: str) -> ExperimentBuilder:
        """Set run strategy.

        Args:
            strategy: NEW, RETRY, BRANCH, RESUME, or MERGE

        Returns:
            Self for chaining
        """
        self._strategy = strategy
        return self

    def with_base(self, base: bool) -> ExperimentBuilder:
        """Set base flag.

        Args:
            base: True if base experiment, False if derived

        Returns:
            Self for chaining
        """
        self._base = base
        return self

    def with_status(self, status: str) -> ExperimentBuilder:
        """Set experiment status.

        Args:
            status: RUNNING, COMPLETED, or FAILED

        Returns:
            Self for chaining
        """
        self._status = status
        return self

    def with_description(self, description: str) -> ExperimentBuilder:
        """Set description.

        Args:
            description: Human-readable description

        Returns:
            Self for chaining
        """
        self._description = description
        return self

    def with_model_uri(self, model_uri: str) -> ExperimentBuilder:
        """Set model URI.

        Args:
            model_uri: Path to model

        Returns:
            Self for chaining
        """
        self._model_uri = model_uri
        return self

    def with_model_id(self, model_id: str) -> ExperimentBuilder:
        """Set model ID.

        Args:
            model_id: Model identifier

        Returns:
            Self for chaining
        """
        self._model_id = model_id
        return self

    def with_codebase(self, codebase: dict[str, str]) -> ExperimentBuilder:
        """Set codebase snapshot.

        Args:
            codebase: Dict of path -> content

        Returns:
            Self for chaining
        """
        self._codebase = dict(codebase)
        return self

    def with_changed_files(self, files: list[str]) -> ExperimentBuilder:
        """Set list of changed files.

        Args:
            files: List of file paths that changed

        Returns:
            Self for chaining
        """
        self._changed_files = list(files)
        return self

    def build(self) -> Experiment:
        """Build the experiment.

        Returns:
            Experiment instance with configured values
        """
        return Experiment(
            id=self._id,
            uri=self._uri,
            strategy=self._strategy,
            base=self._base,
            status=self._status,
            description=self._description,
            model_uri=self._model_uri,
            model_id=self._model_id,
            codebase=self._codebase,
            changed_files=self._changed_files,
            created_at=self._created_at,
            updated_at=self._updated_at,
        )


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointBuilder
# ─────────────────────────────────────────────────────────────────────────────


class CheckpointBuilder:
    """Builder for creating Checkpoint node instances."""

    def __init__(self):
        """Initialize with default values."""
        self._id = str(uuid4())
        self._name = "checkpoint-500"
        self._derived_from = ""
        self._epoch = 1
        self._run = 1
        self._uri = "/output/checkpoint-500"
        self._metrics: dict[str, Any] = {"loss": 0.5}
        self._is_merging = False
        self._created_at = datetime.utcnow()
        self._updated_at = datetime.utcnow()

    def with_id(self, ckp_id: str) -> CheckpointBuilder:
        """Set checkpoint ID.

        Args:
            ckp_id: Checkpoint UUID

        Returns:
            Self for chaining
        """
        self._id = ckp_id
        return self

    def with_name(self, name: str) -> CheckpointBuilder:
        """Set checkpoint name.

        Args:
            name: Checkpoint identifier (e.g., "checkpoint-500")

        Returns:
            Self for chaining
        """
        self._name = name
        return self

    def with_epoch(self, epoch: int) -> CheckpointBuilder:
        """Set epoch number.

        Args:
            epoch: Training epoch

        Returns:
            Self for chaining
        """
        self._epoch = epoch
        return self

    def with_run(self, run: int) -> CheckpointBuilder:
        """Set run number.

        Args:
            run: Run counter

        Returns:
            Self for chaining
        """
        self._run = run
        return self

    def with_uri(self, uri: str) -> CheckpointBuilder:
        """Set checkpoint file URI.

        Args:
            uri: Path to checkpoint file

        Returns:
            Self for chaining
        """
        self._uri = uri
        return self

    def with_metrics(self, metrics: dict[str, Any]) -> CheckpointBuilder:
        """Set training metrics.

        Args:
            metrics: Dict of metric name -> value

        Returns:
            Self for chaining
        """
        self._metrics = dict(metrics)
        return self

    def with_derived_from(self, derived_from: str) -> CheckpointBuilder:
        """Set derivation reference.

        Args:
            derived_from: Reference to source model

        Returns:
            Self for chaining
        """
        self._derived_from = derived_from
        return self

    def with_is_merging(self, is_merging: bool) -> CheckpointBuilder:
        """Set merge flag.

        Args:
            is_merging: True if this is a merge checkpoint

        Returns:
            Self for chaining
        """
        self._is_merging = is_merging
        return self

    def build(self) -> Checkpoint:
        """Build the checkpoint.

        Returns:
            Checkpoint instance with configured values
        """
        return Checkpoint(
            id=self._id,
            name=self._name,
            derived_from=self._derived_from,
            epoch=self._epoch,
            run=self._run,
            uri=self._uri,
            metrics=self._metrics,
            is_merging=self._is_merging,
            created_at=self._created_at,
            updated_at=self._updated_at,
        )


# ─────────────────────────────────────────────────────────────────────────────
# PreRequestBuilder
# ─────────────────────────────────────────────────────────────────────────────


class PreRequestBuilder:
    """Builder for creating PreRequest API payloads."""

    def __init__(self):
        """Initialize with default values."""
        self._experiment_name = "test-experiment"
        self._experiment_uri = "/tmp/test-project"
        self._base_experiment_id: str | None = None
        self._previous_experiment_id: str | None = None
        self._description: str | None = None
        self._model_uri = "/nfs/llama-7b"
        self._model_id = "llama-7b-base"
        self._codebase: dict[str, str] = {
            "train.py": "import torch",
            "config.yaml": "model: llama",
        }
        self._checkpoint_resume_from: str | None = None

    def with_experiment_name(self, name: str) -> PreRequestBuilder:
        """Set experiment name.

        Args:
            name: Experiment name

        Returns:
            Self for chaining
        """
        self._experiment_name = name
        return self

    def with_experiment_uri(self, uri: str) -> PreRequestBuilder:
        """Set experiment URI.

        Args:
            uri: Project URI

        Returns:
            Self for chaining
        """
        self._experiment_uri = uri
        return self

    def with_base_experiment_id(self, exp_id: str | None) -> PreRequestBuilder:
        """Set base experiment ID.

        Args:
            exp_id: Parent experiment ID or None

        Returns:
            Self for chaining
        """
        self._base_experiment_id = exp_id
        return self

    def with_previous_experiment_id(self, exp_id: str | None) -> PreRequestBuilder:
        """Set previous experiment ID.

        Args:
            exp_id: Previous experiment ID or None

        Returns:
            Self for chaining
        """
        self._previous_experiment_id = exp_id
        return self

    def with_description(self, description: str | None) -> PreRequestBuilder:
        """Set description.

        Args:
            description: Description or None

        Returns:
            Self for chaining
        """
        self._description = description
        return self

    def with_model_uri(self, uri: str) -> PreRequestBuilder:
        """Set model URI.

        Args:
            uri: Path to model

        Returns:
            Self for chaining
        """
        self._model_uri = uri
        return self

    def with_model_id(self, model_id: str) -> PreRequestBuilder:
        """Set model ID.

        Args:
            model_id: Model identifier

        Returns:
            Self for chaining
        """
        self._model_id = model_id
        return self

    def with_codebase(self, codebase: dict[str, str]) -> PreRequestBuilder:
        """Set codebase files.

        Args:
            codebase: Dict of path -> content

        Returns:
            Self for chaining
        """
        self._codebase = dict(codebase)
        return self

    def with_checkpoint_resume_from(self, checkpoint_id: str | None) -> PreRequestBuilder:
        """Set checkpoint to resume from.

        Args:
            checkpoint_id: Checkpoint ID or None

        Returns:
            Self for chaining
        """
        self._checkpoint_resume_from = checkpoint_id
        return self

    def build(self) -> dict[str, Any]:
        """Build the request payload.

        Returns:
            Dict ready for JSON serialization in API request
        """
        payload: dict[str, Any] = {
            "experiment_name": self._experiment_name,
            "experiment_uri": self._experiment_uri,
            "model_uri": self._model_uri,
            "model_id": self._model_id,
            "codebase": self._codebase,
        }
        if self._base_experiment_id is not None:
            payload["base_experiment_id"] = self._base_experiment_id
        if self._previous_experiment_id is not None:
            payload["previous_experiment_id"] = self._previous_experiment_id
        if self._description is not None:
            payload["description"] = self._description
        if self._checkpoint_resume_from is not None:
            payload["checkpoint_resume_from"] = self._checkpoint_resume_from
        return payload


# ─────────────────────────────────────────────────────────────────────────────
# ConfigBuilder
# ─────────────────────────────────────────────────────────────────────────────


class ConfigBuilder:
    """Builder for creating LineageConfig instances."""

    def __init__(self):
        """Initialize with default values."""
        self._experiment_name = "test-experiment"
        self._experiment_uri = "/tmp/test-project"
        self._checkpoint_resume_from: str | None = None
        self._model_uri = "/nfs/llama-7b"
        self._model_id = "llama-7b-base"
        self._output_dir = "/tmp/output"
        self._merging_enabled = False
        self._merge_method: str | None = None
        self._merge_sources: list[str] = []

    def with_experiment_name(self, name: str) -> ConfigBuilder:
        """Set experiment name.

        Args:
            name: Experiment name

        Returns:
            Self for chaining
        """
        self._experiment_name = name
        return self

    def with_experiment_uri(self, uri: str) -> ConfigBuilder:
        """Set experiment URI.

        Args:
            uri: Project URI

        Returns:
            Self for chaining
        """
        self._experiment_uri = uri
        return self

    def with_checkpoint_resume_from(self, checkpoint_id: str | None) -> ConfigBuilder:
        """Set checkpoint to resume from.

        Args:
            checkpoint_id: Checkpoint ID or None

        Returns:
            Self for chaining
        """
        self._checkpoint_resume_from = checkpoint_id
        return self

    def with_model_uri(self, uri: str) -> ConfigBuilder:
        """Set model URI.

        Args:
            uri: Path to model

        Returns:
            Self for chaining
        """
        self._model_uri = uri
        return self

    def with_model_id(self, model_id: str) -> ConfigBuilder:
        """Set model ID.

        Args:
            model_id: Model identifier

        Returns:
            Self for chaining
        """
        self._model_id = model_id
        return self

    def with_output_dir(self, output_dir: str) -> ConfigBuilder:
        """Set output directory.

        Args:
            output_dir: Path to output directory

        Returns:
            Self for chaining
        """
        self._output_dir = output_dir
        return self

    def with_model_merging_enabled(self, enabled: bool) -> ConfigBuilder:
        """Enable/disable model merging.

        Args:
            enabled: True to enable merging

        Returns:
            Self for chaining
        """
        self._merging_enabled = enabled
        return self

    def with_merge_method(self, method: str) -> ConfigBuilder:
        """Set merge method.

        Args:
            method: Merge method name (e.g., "linear")

        Returns:
            Self for chaining
        """
        self._merge_method = method
        return self

    def with_merge_sources(self, sources: list[str]) -> ConfigBuilder:
        """Set merge sources.

        Args:
            sources: List of source model identifiers

        Returns:
            Self for chaining
        """
        self._merge_sources = list(sources)
        return self

    def build(self) -> LineageConfig:
        """Build the config.

        Returns:
            LineageConfig instance with configured values
        """
        # Use default merge_method if not set
        merge_method = self._merge_method or ("linear" if self._merging_enabled else "")

        return LineageConfig(
            experiment=ExperimentConfig(
                name=self._experiment_name,
                uri=self._experiment_uri,
                checkpoint_resume_from=self._checkpoint_resume_from,
            ),
            model={
                "model_uri": self._model_uri,
                "model_id": self._model_id,
            },
            output=OutputConfig(output_dir=self._output_dir),
            model_merging=ModelMergingConfig(
                enabled=self._merging_enabled,
                merge_method=merge_method,
                sources=self._merge_sources,
            ),
        )
