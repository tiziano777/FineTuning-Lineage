"""FAKE train.py — Used to test lineage operations without actually training a model."""

from __future__ import annotations
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

import sys
from pathlib import Path
from typing import Any, Dict

from modules.utils.config_validator import load_config, require_field, resolve_config
from modules.lineage.utils.callbacks import LineageCheckpointCallback
from modules.lineage import lineage_tracker
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Fake Trainer Objects (Simulate Hugging Face structures for the callback)
# ---------------------------------------------------------------------------

class FakeArgs:
    """Simulates TrainingArguments required by the callback."""
    def __init__(self, output_dir: str):
        self.output_dir = output_dir

class FakeTrainerState:
    """Simulates TrainerState required by the callback."""
    def __init__(self, epoch: float, best_model_checkpoint: str | None, log_history: list[Dict[str, Any]]):
        self.epoch = epoch
        self.best_model_checkpoint = best_model_checkpoint
        self.log_history = log_history

class TrainerFakeWithCallbackTrigger:
    """
    A fake trainer that completely bypasses PyTorch/Transformers training 
    and manually triggers the lineage checkpoint callback to test the lineage system.
    """
    def __init__(self, output_dir: str, callbacks: list | None = None):
        self.output_dir = output_dir
        self.callbacks = callbacks or []

    def train(self):
        logger.info("🤖 Starting FAKE Training Loop...")
        
        # Se non ci sono callback, usciamo subito
        if not self.callbacks:
            logger.warning("No callbacks registered. Exiting fake train.")
            return

        # -------------------------------------------------------------------
        # Simulazione Chiamata 1: Checkpoint di metà percorso (Epoch 1)
        # -------------------------------------------------------------------
        logger.info("Simulating Step 100 / Epoch 1.0 ...")
        args_1 = FakeArgs(output_dir=self.output_dir)
        state_1 = FakeTrainerState(
            epoch=1.0,
            best_model_checkpoint=str(Path(self.output_dir) / "checkpoint-100"),
            log_history=[{"loss": 0.42, "eval_loss": 0.45, "step": 100}]
        )
        
        for callback in self.callbacks:
            if hasattr(callback, "on_save"):
                callback.on_save(args=args_1, state=state_1, control=None)

        # -------------------------------------------------------------------
        # Simulazione Chiamata 2: Checkpoint Finale (Epoch 2)
        # -------------------------------------------------------------------
        logger.info("Simulating Step 200 / Epoch 2.0 (End of Train) ...")
        args_2 = FakeArgs(output_dir=self.output_dir)
        state_2 = FakeTrainerState(
            epoch=2.0,
            best_model_checkpoint=str(Path(self.output_dir) / "checkpoint-200"),
            log_history=[{"loss": 0.19, "eval_loss": 0.22, "step": 200}]
        )
        
        for callback in self.callbacks:
            if hasattr(callback, "on_save"):
                callback.on_save(args=args_2, state=state_2, control=None)

        # -------------------------------------------------------------------
        # Fine Addestramento: Trigger on_train_end per chiudere i connettori
        # -------------------------------------------------------------------
        logger.info("Simulating Training End...")
        for callback in self.callbacks:
            if hasattr(callback, "on_train_end"):
                callback.on_train_end(args=args_2, state=state_2, control=None)

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

@lineage_tracker(capture_checkpoints=True) # False for testing without ckp callback
def train(config_path: str = "config.yml", dry_run: bool = False, lineage_callback=None):
    logger.info("Starting DPO training with config: %s", config_path)
    ctx = preflight(config_path)

    if dry_run:
        logger.info("Dry run complete — all checks passed.")
        return

    config = ctx["config"]
    model_id = ctx["model_id"]
    output_dir = ctx["output_dir"]
    model_uri = ctx["model_uri"]
    ref_model = ctx["ref_model"]
    precompute_ref_log_probs = ctx["precompute_ref_log_probs"]
    training_cfg = ctx["training_cfg"]

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------
    callbacks = []

    # Lineage callback (already instantiated by decorator)
    if lineage_callback is not None:
        callbacks.append(lineage_callback)

    # -----------------------------------------------------------------------
    # Trainer
    # -----------------------------------------------------------------------
    trainer =  TrainerFakeWithCallbackTrigger(output_dir=output_dir, callbacks=callbacks if callbacks else None)
    trainer.train()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    cfg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "config.yml"
    train(cfg, dry_run=dry)
