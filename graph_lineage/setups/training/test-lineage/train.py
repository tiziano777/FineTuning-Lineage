"""FAKE train.py — Used to test lineage operations without actually training a model."""

from __future__ import annotations
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

import sys
from pathlib import Path
from typing import Any, Dict

from modules.utils.config_validator import load_config, require_field, resolve_config
from modules.lineage.tracker import lineage_tracker
from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight(config_path: str) -> Dict[str, Any]:
    """
    Validate configs before training starts,
    load dataset, check columns and return context for training.
    """
    config = load_config(config_path)
    config = resolve_config(config)

    # Required model fields
    model_id = require_field(config, "model", "model_id", config_file=config_path)
    model_uri = config.get("model", {}).get("model_uri")
    cache_dir = require_field(config, "model", "dataset", "cache_dir", config_file=config_path)
    filtered_samples = require_field(config, "model", "dataset", "filtered_samples", config_file=config_path)

    # Training fields
    training_cfg = require_field(config, "model", "training", config_file=config_path)
    require_field(config, "model", "training", "per_device_train_batch_size", config_file=config_path)
    require_field(config, "model", "training", "gradient_accumulation_steps", config_file=config_path)
    require_field(config, "model", "training", "learning_rate", config_file=config_path)
    require_field(config, "model", "training", "beta", config_file=config_path)
    require_field(config, "model", "training", "num_train_epochs", config_file=config_path)
    require_field(config, "model", "training", "logging_steps", config_file=config_path)
    require_field(config, "model", "training", "max_length", config_file=config_path)
    require_field(config, "model", "training", "max_prompt_length", config_file=config_path)
    require_field(config, "model", "training", "bf16", config_file=config_path)
    require_field(config, "model", "training", "gradient_checkpointing", config_file=config_path)

    ref_model = config.get("model", {}).get("training", {}).get("ref_model")
    output_dir = require_field(config, "output", "output_dir", config_file=config_path)
    plot_dir = require_field(config, "output", "plot_dir", config_file=config_path)
    precompute_ref_log_probs = require_field(config, "model", "training", "precompute_ref_log_probs", config_file=config_path)

    # Cache existence
    '''cache_path = Path(cache_dir)
    if not cache_path.exists():
        raise FileNotFoundError(f"Cache not found: {cache_path}. Run prepare.py first.")
    '''
    # TRAIN EVAL SPLIT
    eval_size = config.get("model", {}).get("training", {}).get("eval_size", 0)

    return {
        "model_id": model_id, "config": config,
        "dataset": None, "output_dir": output_dir,
        "training_cfg": training_cfg, "cache_path": str(Path(cache_dir)),
        "filtered_samples": filtered_samples, "model_uri": model_uri,
        "ref_model": ref_model, "precompute_ref_log_probs": precompute_ref_log_probs,
        "plot_dir": plot_dir
    }


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

@lineage_tracker()
def train(
    config_path: str = "config.yml",
    dry_run: bool = False,
    lineage_emit=None,
):
    """Simulated training function.

    Args:
        config_path: Path to the training configuration.
        dry_run: If True, skip actual training.
        lineage_emit: Manual emit function for ad-hoc node creation.
    """
    print(f"Starting training with config: {config_path}")

    if dry_run:
        print("Dry run mode — no training performed.")
        return

    # -----------------------------------------------------------------------
    # Simulazione: Epoch 1 — Checkpoint intermedio
    # -----------------------------------------------------------------------
    logger.info("Simulating Step 100 / Epoch 1.0 ...")
    if lineage_emit:
        lineage_emit(
            "Checkpoint",
            {
                "name": "checkpoint-100",
                "epoch": 1,
                "run": 1,
                "uri": "s3://bucket/run-123/checkpoint-100",
                "metrics": '{"loss": 0.42, "eval_loss": 0.45, "step": 100}',
                "derived_from": "",
                "is_merging": False,
            },
            "produced",
        )

    # -----------------------------------------------------------------------
    # Simulazione: Epoch 2 — Checkpoint finale
    # -----------------------------------------------------------------------
    logger.info("Simulating Step 200 / Epoch 2.0 (End of Train) ...")
    if lineage_emit:
        lineage_emit(
            "Checkpoint",
            {
                "name": "checkpoint-200",
                "epoch": 2,
                "run": 1,
                "uri": "s3://bucket/run-123/checkpoint-200",
                "metrics": '{"loss": 0.19, "eval_loss": 0.22, "step": 200}',
                "derived_from": "checkpoint-100",
                "is_merging": False,
            },
            "produced",
        )

    print("Training completed.")
    return {"metrics_uri": "s3://bucket/run-123/metrics.json"}


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    cfg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "config.yml"
    train(cfg, dry_run=dry)