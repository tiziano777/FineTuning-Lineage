"""train.py — DPO training entry point.
Loads prepared data from cache, validates configuration,
and runs a pre-flight check before invoking a suitable trainer.
"""
from __future__ import annotations
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s" )
logger = logging.getLogger(__name__)

import sys
from pathlib import Path
from typing import Any, Dict
import os

import torch
from trl import DPOConfig, DPOTrainer
from huggingface_hub import login
from transformers import AutoTokenizer

from modules.loader.data_loader import DataLoader
from modules.loader.model_loader import ModelLoader
from modules.utils.config_validator import load_config, require_field, resolve_config
from modules.plots.plot_manager import PlotManager
from modules.callbacks.metrics_saver import MetricsSaverCallback
from modules.lineage import lineage_tracker
from dotenv import load_dotenv
load_dotenv()

# HF TOKEN
hf_token = os.getenv('HF_TOKEN')
if hf_token:
    try:
        # Effettua il login in modo silenzioso senza richiedere input interattivi
        login(token=hf_token, add_to_git_credential=False)
        print("HF LOGIN SUCCESS: Autenticazione con Hugging Face completata correttamente.")
    except Exception as e:
        print(f"HF LOGIN WARNING: Errore durante il login con il token fornito: {e}")
else:
    print("HF LOGIN INFO: Nessun HF_TOKEN trovato nel file .env. L'accesso ai repo privati non sarà disponibile.")

# CUDA info
logger.info("CUDA available: %s", torch.cuda.is_available())
if torch.cuda.is_available():
    logger.info("Device: %s (%d GB)", torch.cuda.get_device_name(0),torch.cuda.get_device_properties(0).total_memory // (1024**3))

def preflight(config_path: str) -> Dict[str, Any]:
    """
    Validate configs before training starts,
    load dataset, check columns and return context for training.
    """
    
    config = load_config(config_path)
    config = resolve_config(config)

    # Required model fields
    model_id = require_field(config, "model", "model_id", config_file=config_path)
    # model_uri is optional in config; required only when explicitly loading from a URI/local repo
    model_uri = config.get("model", {}).get("model_uri")
    cache_dir = require_field(config, "model","dataset", "cache_dir", config_file=config_path)
    # how to store out of cointext samples for filtering (if enabled)
    filtered_samples = require_field(config, "model","dataset", "filtered_samples", config_file=config_path)
    
    # Training fields
    training_cfg = require_field(config, "model", "training", config_file=config_path)
    # Ensure minimal training keys exist (others optional)
    require_field(config, "model", "training", "per_device_train_batch_size", config_file=config_path)
    require_field(config, "model", "training", "gradient_accumulation_steps", config_file=config_path)
    require_field(config, "model", "training", "learning_rate", config_file=config_path)
    require_field(config, "model", "training", "beta", config_file=config_path)
    #require_field(config, "model", "training", "max_steps", config_file=config_path)
    require_field(config, "model", "training", "num_train_epochs", config_file=config_path)
    require_field(config, "model", "training", "logging_steps", config_file=config_path)
    require_field(config, "model", "training", "max_length", config_file=config_path)
    require_field(config, "model", "training", "max_prompt_length", config_file=config_path)
    require_field(config, "model", "training", "bf16", config_file=config_path)
    require_field(config, "model", "training", "torch_dtype", config_file=config_path)
    require_field(config, "model", "training", "gradient_checkpointing", config_file=config_path)
    
    ref_model= config.get("model", {}).get("training", {}).get("ref_model")  # optional; if not set, DPOTrainer defaults to model for ref as well
    # Output Dir
    output_dir = require_field(config, "output", "output_dir", config_file=config_path)
    plot_dir = require_field(config, "output", "plot_dir", config_file=config_path)
    precompute_ref_log_probs = require_field(config, "model","training", "precompute_ref_log_probs", config_file=config_path)

    # Cache existence
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        raise FileNotFoundError(f"Cache not found: {cache_path}. Run prepare.py first.")
    
    # TRAIN EVAL SPLIT
    eval_size = config.get("model", {}).get("training", {}).get("eval_size", 0)
    ds_train, ds_eval = DataLoader.load_cached_dataset(cache_path, eval_size=eval_size, is_arrow=True)

    # CHECK for columns presence for DPO
    required_cols = {"prompt", "chosen", "rejected"}
    cols = set(getattr(ds_train, 'column_names', []))
    missing = required_cols - cols
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")
    logger.info("Dataset OK: %d rows, columns: %s", len(ds_train), ds_train.column_names)

    return {
        "model_id": model_id, "config": config,
        "dataset": (ds_train, ds_eval), "output_dir": output_dir,
        "training_cfg": training_cfg, "cache_path": str(cache_path),
        "filtered_samples": filtered_samples, "model_uri": model_uri,
        "ref_model": ref_model, "precompute_ref_log_probs": precompute_ref_log_probs, "plot_dir": plot_dir
    }

@lineage_tracker(capture_checkpoints=True)
def train(config_path: str = "config.yml", dry_run: bool = False, lineage_callback=None):
    ctx = preflight(config_path)

    if dry_run:
        logger.info("Dry run complete — all checks passed.")
        return

    config = ctx["config"]
    model_id = ctx["model_id"]
    ds_train, ds_eval = ctx["dataset"]
    output_dir = ctx["output_dir"]
    model_uri = ctx["model_uri"]
    ref_model = ctx["ref_model"]
    precompute_ref_log_probs = ctx["precompute_ref_log_probs"]

    training_cfg = ctx["training_cfg"]

    source = model_uri or model_id

    # Model + Tokenizer + PEFT (all handled by ModelLoader)
    loader = ModelLoader(hf_token=hf_token)
    peft_cfg = config.get('model', {}).get('peft')
    model, tokenizer = loader.load_model(
        model_id=model_id,
        model_uri=source,
        torch_dtype=training_cfg["torch_dtype"],
        device_map=training_cfg.get("device_map"),
        peft_cfg=peft_cfg
    )

    # Tokenizer (re)initialization with local_files_only to avoid unwanted downloads during training runs
    # Base tokenizer is loaded, if a known LLM is used, you can omit tokenizer_class.
    tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True, tokenizer_class="PreTrainedTokenizerFast")
    tokenizer.init_kwargs["tokenizer_class"] = "PreTrainedTokenizerFast"
    # Forza l'allineamento del pad token sull'EOS 
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.pad_token_id = tokenizer.eos_token_id
    # direzione del padding
    tokenizer.padding_side = "right" 
    model.config.pad_token_id = tokenizer.eos_token_id

    dpo_args = {
        'output_dir': output_dir,
        'per_device_train_batch_size': training_cfg.get('per_device_train_batch_size'),
        'gradient_accumulation_steps': training_cfg.get('gradient_accumulation_steps'),
        "gradient_checkpointing":training_cfg.get("gradient_checkpointing"),
        'precompute_ref_log_probs': precompute_ref_log_probs,

        # PULIZIA COLONNE AUTOMATICA
        'remove_unused_columns': training_cfg.get('remove_unused_columns'),
        
        # ⚡ VELOCIZZAZIONE TOKENIZZAZIONE 
        'dataset_num_proc': int(os.cpu_count()*0.67), 
        
        # LIMITI DI LUNGHEZZA (Importanti per evitare i warning/crash visti all'inizio)
        'max_length': training_cfg.get('max_length', 8192),       
        'max_prompt_length': training_cfg.get('max_prompt_length', 2048),

        # Altri parametri standard
        'max_steps': training_cfg.get('max_steps'),
        'learning_rate': float(training_cfg.get('learning_rate')),
        'beta': float(training_cfg.get('beta')),
        'logging_steps': training_cfg.get('logging_steps'),
        'save_steps': training_cfg.get('save_steps'),
        'bf16': training_cfg.get('bf16', True),
        'report_to': training_cfg.get('report_to', 'none'),

        'evaluation_strategy': training_cfg.get('evaluation_strategy', 'steps'),
        
        # NO file .pt dell'ottimizzatore 
        'save_only_model': True, 
    }

    # Rimuovi i valori None e crea la config
    training_args = DPOConfig(**{k: v for k, v in dpo_args.items() if v is not None})

    # METRICS CALLBACK
    metrics_uri = config.get("output", {}).get("metrics_uri")
    callbacks = []
    if metrics_uri:
        metrics_saver = MetricsSaverCallback(metrics_path=Path(metrics_uri))
        callbacks.append(metrics_saver)

    if lineage_callback is not None:
        callbacks.append(lineage_callback)

    # TRAINER
    trainer = DPOTrainer(
        model=model,
        ref_model=ref_model,
        args=training_args,
        train_dataset=ds_train,
        eval_dataset=ds_eval,
        tokenizer=tokenizer,
        callbacks=callbacks if callbacks else None,
    )

    logger.info(str(dpo_args))
    logger.info("Starting DPO training...")

    trainer.args.max_shard_size = "1GB"
    trainer.train()
    logger.info("Training complete. Saved to %s", output_dir)


    # -- generate diagnostic plots from training history --
    try:
        beta = training_cfg.get('beta', 0.1)
        max_grad_norm = training_cfg.get('max_grad_norm', 1.0)
        plot_dir = config.get("output", {}).get("plot_dir")
        pm = PlotManager(config_path=config_path, beta=beta, max_grad_norm=max_grad_norm, output_base=plot_dir)
        plots_log = pm.run(trainer.state.log_history)
        logger.info('Plots logs saved to %s', plots_log)
    except Exception:
        logger.exception('Plot generation failed (non-fatal); training artefacts are intact.')

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    cfg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "config.yml"
    train(cfg, dry_run=dry)
