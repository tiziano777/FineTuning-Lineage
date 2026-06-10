"""merge.py — Model merging via checkpoint averaging.

Supports two modes governed by model_merging.lora_enabled:
  - Full-weight merge: averages N complete model state_dicts
  - LoRA merge: averages N adapter weights, then either merges into base or saves adapter

Usage:
    python merge.py config.yml
"""

from __future__ import annotations

import gc
import logging
import os
import shutil
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_base"))

from modules.lineage import lineage_tracker
from modules.utils.config_validator import load_config, require_field, resolve_config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ---------------------------------------------------------------------------
# Dtype mapping
# ---------------------------------------------------------------------------

DTYPE_MAP = {
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}

# ---------------------------------------------------------------------------
# Preflight validation
# ---------------------------------------------------------------------------

def preflight(config_path: str) -> dict:
    """Validate config and return execution context."""
    config = load_config(config_path)
    config = resolve_config(config)

    # Required fields
    require_field(config, "model_merging", "enabled", config_file=config_path)
    merge_method = require_field(config, "model_merging", "merge_method", config_file=config_path)
    sources = require_field(config, "model_merging", "sources", config_file=config_path)
    output_dir = require_field(config, "output", "output_dir", config_file=config_path)

    lora_enabled = config["model_merging"].get("lora_enabled", False)

    # Validate merge_method
    supported_methods = ("avg",)
    if merge_method not in supported_methods:
        raise ValueError(
            f"Unsupported merge_method '{merge_method}'. Supported: {supported_methods}"
        )

    # Validate sources
    if not isinstance(sources, list) or len(sources) < 2:
        raise ValueError("model_merging.sources must be a list with at least 2 entries.")

    for src in sources:
        if not Path(src).exists():
            raise ValueError(f"Source path does not exist: {src}")

    # LoRA-specific validation
    merge_strategy = None
    base_model_path = None
    if lora_enabled:
        base_model_path = require_field(
            config, "model_merging", "lora", "base_model_path", config_file=config_path
        )
        merge_strategy = require_field(
            config, "model_merging", "lora", "merge_strategy", config_file=config_path
        )
        if merge_strategy not in ("fully_merged_model", "adapter_only"):
            raise ValueError(
                f"Invalid lora.merge_strategy '{merge_strategy}'. "
                "Must be 'fully_merged_model' or 'adapter_only'."
            )
        if not Path(base_model_path).exists():
            raise ValueError(f"lora.base_model_path does not exist: {base_model_path}")

    # Dtype
    save_dtype_str = config["model_merging"].get("save_dtype", "float16")
    torch_dtype_str = config["model_merging"].get("torch_dtype", "float16")

    if save_dtype_str not in DTYPE_MAP:
        raise ValueError(f"Invalid save_dtype '{save_dtype_str}'. Use: {list(DTYPE_MAP.keys())}")
    if torch_dtype_str not in DTYPE_MAP:
        raise ValueError(f"Invalid torch_dtype '{torch_dtype_str}'. Use: {list(DTYPE_MAP.keys())}")

    return {
        "config": config,
        "merge_method": merge_method,
        "sources": sources,
        "output_dir": output_dir,
        "lora_enabled": lora_enabled,
        "base_model_path": base_model_path,
        "merge_strategy": merge_strategy,
        "save_dtype": DTYPE_MAP[save_dtype_str],
        "torch_dtype": DTYPE_MAP[torch_dtype_str],
    }

# ---------------------------------------------------------------------------
# Full-weight merge
# ---------------------------------------------------------------------------

def _find_safetensors(model_dir: str) -> list[str]:
    """Find all safetensors shard files in a model directory."""
    p = Path(model_dir)
    files = sorted(p.glob("*.safetensors"))
    if not files:
        raise FileNotFoundError(f"No .safetensors files found in {model_dir}")
    return [str(f) for f in files]

def _get_shard_names(model_dir: str) -> list[str]:
    """Get relative shard filenames from a model directory."""
    p = Path(model_dir)
    return sorted(f.name for f in p.glob("*.safetensors"))

def merge_full_weights(sources: list[str], output_dir: str, save_dtype: torch.dtype, torch_dtype: torch.dtype):
    """Average N full model state_dicts and save as HF model."""
    logger.info("Starting full-weight merge of %d models", len(sources))
    n = len(sources)

    # Get shard structure from first source
    shard_names = _get_shard_names(sources[0])

    # Average shard by shard to limit memory usage
    os.makedirs(output_dir, exist_ok=True)

    for shard_name in shard_names:
        logger.info("  Averaging shard: %s", shard_name)

        # Load and accumulate
        accumulated = None
        for i, src in enumerate(sources):
            shard_path = str(Path(src) / shard_name)
            if not Path(shard_path).exists():
                raise FileNotFoundError(f"Shard {shard_name} missing in {src}")

            state_dict = load_file(shard_path)

            if accumulated is None:
                accumulated = {k: v.to(torch.float32) for k, v in state_dict.items()}
            else:
                for k, v in state_dict.items():
                    accumulated[k].add_(v.to(torch.float32))

            del state_dict
            gc.collect()

        # Divide by N and cast to save_dtype
        for k in accumulated:
            accumulated[k] = (accumulated[k] / n).to(save_dtype)

        # Save averaged shard
        save_file(accumulated, str(Path(output_dir) / shard_name))
        del accumulated
        gc.collect()

    # Copy non-weight files from first source (config.json, tokenizer, etc.)
    first_source = Path(sources[0])
    for f in first_source.iterdir():
        if f.suffix != ".safetensors" and f.name != ".DS_Store":
            dest = Path(output_dir) / f.name
            if f.is_file():
                shutil.copy2(f, dest)
            elif f.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(f, dest)

    logger.info("Full-weight merge complete. Output: %s", output_dir)

# ---------------------------------------------------------------------------
# LoRA adapter merge
# ---------------------------------------------------------------------------

def _load_adapter_state_dict(adapter_dir: str) -> dict[str, torch.Tensor]:
    """Load adapter weights from a PEFT adapter directory."""
    adapter_path = Path(adapter_dir)

    # Try safetensors first, then bin
    safetensors_file = adapter_path / "adapter_model.safetensors"
    bin_file = adapter_path / "adapter_model.bin"

    if safetensors_file.exists():
        return load_file(str(safetensors_file))
    elif bin_file.exists():
        return torch.load(str(bin_file), map_location="cpu", weights_only=True)
    else:
        raise FileNotFoundError(
            f"No adapter_model.safetensors or adapter_model.bin in {adapter_dir}"
        )

def merge_lora_adapters(
    sources: list[str],
    base_model_path: str,
    output_dir: str,
    merge_strategy: str,
    save_dtype: torch.dtype,
    torch_dtype: torch.dtype,
):
    """Average N LoRA adapters and produce merged output."""
    from peft import PeftModel

    logger.info("Starting LoRA merge of %d adapters (strategy: %s)", len(sources), merge_strategy)
    n = len(sources)

    # 1. Average adapter weights
    accumulated = None
    for i, src in enumerate(sources):
        logger.info("  Loading adapter %d/%d: %s", i + 1, n, src)
        state_dict = _load_adapter_state_dict(src)

        if accumulated is None:
            accumulated = {k: v.to(torch.float32) for k, v in state_dict.items()}
        else:
            for k, v in state_dict.items():
                if k in accumulated:
                    accumulated[k].add_(v.to(torch.float32))
                else:
                    logger.warning("Key %s not in first adapter, skipping", k)

        del state_dict
        gc.collect()

    # Divide by N
    for k in accumulated:
        accumulated[k] = (accumulated[k] / n).to(save_dtype)

    os.makedirs(output_dir, exist_ok=True)

    if merge_strategy == "adapter_only":
        # Save averaged adapter weights + copy config from first source
        logger.info("Saving averaged adapter to %s", output_dir)
        save_file(accumulated, str(Path(output_dir) / "adapter_model.safetensors"))

        # Copy adapter_config.json from first source
        src_config = Path(sources[0]) / "adapter_config.json"
        if src_config.exists():
            shutil.copy2(src_config, Path(output_dir) / "adapter_config.json")
        else:
            logger.warning("adapter_config.json not found in %s", sources[0])

    elif merge_strategy == "fully_merged_model":
        # Save temporary adapter, load with PeftModel, merge_and_unload, save full model
        tmp_adapter_dir = Path(output_dir) / "_tmp_averaged_adapter"
        tmp_adapter_dir.mkdir(parents=True, exist_ok=True)

        save_file(accumulated, str(tmp_adapter_dir / "adapter_model.safetensors"))

        # Copy adapter_config.json from first source
        src_config = Path(sources[0]) / "adapter_config.json"
        if src_config.exists():
            shutil.copy2(src_config, tmp_adapter_dir / "adapter_config.json")
        else:
            raise FileNotFoundError(f"adapter_config.json required but not found in {sources[0]}")

        del accumulated
        gc.collect()

        # Load base model
        logger.info("Loading base model: %s", base_model_path)
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_path, torch_dtype=torch_dtype, device_map="cpu"
        )

        # Load averaged adapter onto base
        logger.info("Applying averaged adapter and merging...")
        model = PeftModel.from_pretrained(base_model, str(tmp_adapter_dir))
        model = model.merge_and_unload()

        # Save merged model
        logger.info("Saving fully merged model to %s", output_dir)
        model.save_pretrained(output_dir, safe_serialization=True)

        # Save tokenizer
        tokenizer = AutoTokenizer.from_pretrained(base_model_path)
        tokenizer.save_pretrained(output_dir)

        # Cleanup temp
        shutil.rmtree(tmp_adapter_dir)

        del model, base_model
        gc.collect()

    logger.info("LoRA merge complete. Output: %s", output_dir)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@lineage_tracker()
def merge(config_path: str = "config.yml"):
    """Main merge function with lineage tracking."""
    ctx = preflight(config_path)

    if ctx["lora_enabled"]:
        merge_lora_adapters(
            sources=ctx["sources"],
            base_model_path=ctx["base_model_path"],
            output_dir=ctx["output_dir"],
            merge_strategy=ctx["merge_strategy"],
            save_dtype=ctx["save_dtype"],
            torch_dtype=ctx["torch_dtype"],
        )
    else:
        merge_full_weights(
            sources=ctx["sources"],
            output_dir=ctx["output_dir"],
            save_dtype=ctx["save_dtype"],
            torch_dtype=ctx["torch_dtype"],
        )

    logger.info("Merge completed successfully.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python merge.py <config.yml>")
        sys.exit(1)

    merge(config_path=sys.argv[1])

