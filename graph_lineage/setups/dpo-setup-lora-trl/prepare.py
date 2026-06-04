"""prepare.py — Build DPO training cache from recipe.

Pipeline:
  1. Load recipe config (entries with dist_uri, replica, system_prompt, chat_type)
  2. For each entry: load data -> replicate -> assign system prompts -> apply template
  3. Save processed dataset to .cache/
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

from datasets import Dataset, DatasetDict

from modules.recipe.recipe_loader import RecipeLoader
from modules.loader.data_loader import DataLoader
from modules.system_prompt.assigner import SystemPromptAssigner, PromptAssignmentStrategy
from modules.templates.chat_type_registry import ChatTypeRegistry
from modules.utils.config_validator import load_config, require_field, resolve_config
from modules.loader.model_loader import get_local_tokenizer
from modules.filters.filter_by_token_len import filter_by_token
from modules.filters.hard_negative_filtering import HardNegativeFilter, HardNegativeConfig
from modules.shuffle.shuffler import DatasetShuffler, ShuffleStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def prepare(config_path: str,strategy: PromptAssignmentStrategy = PromptAssignmentStrategy.ALL) -> Path:
    
    config = load_config(config_path)
    config = resolve_config(config=config, experiment_path= config.get("model", {}).get("lineage_uri"))

    cache_dir = Path(require_field(config, "model","dataset", "cache_dir", config_file=config_path))
    templates_mapping = require_field(config, "model", "dataset", "templates_mapping", config_file=config_path)
    temperature = require_field(config, "model", "dataset", "rejected_temperature", config_file=config_path)

    recipe = RecipeLoader.load(config_path)
    logger.info("Loaded recipe: %d entries", len(recipe.entries))

    registry = ChatTypeRegistry(templates_mapping)

    strategy_str = (config.get("model", {}).get("dataset", {}).get("prompt_strategy")or config.get("model", {}).get("dataset", {}).get("promptt_strategy"))
    if isinstance(strategy_str, str):
        try:
            strategy = PromptAssignmentStrategy(strategy_str.lower())
        except ValueError:
            logger.warning("Unknown prompt strategy '%s' in config, using default %s",strategy_str,PromptAssignmentStrategy.ALL)
            strategy = PromptAssignmentStrategy.ALL
    else:
        strategy = strategy

    logger.info("Prompt assignment strategy: %s", strategy)
    assigner = SystemPromptAssigner(strategy)

    # Hard Negative Filter setup
    dataset_cfg = config.get("model", {}).get("dataset", {})
    hn_enabled = dataset_cfg.get("hard_negative_enabled", True)
    hn_params = dataset_cfg.get("hard_negative_params", {})

    all_samples: list[dict] = []
    dropped=0
    for uri, entry in recipe.entries.items():
        hn_filter_instance = None
        hn_filter_entry_stats = None
        if hn_enabled:
            hn_config = HardNegativeConfig(uri=uri)
            hn_filter_entry_stats = hn_config.get_config(entry_uri=entry.dist_uri)
            # Inject weights from config.yml into filter config
            if hn_params:
                hn_filter_entry_stats["w_entropy"] = hn_params.get("w1", 0.2)
                hn_filter_entry_stats["w_ttr"] = hn_params.get("w2", 0.2)
                hn_filter_entry_stats["w_rouge_dist"] = hn_params.get("w3", 0.4)
                hn_filter_entry_stats["w_length_pen"] = hn_params.get("w4", 0.2)
                hn_filter_entry_stats["fallback"] = hn_params.get("config_based_fallback", "temperature")
                hn_filter_entry_stats["use_length_penalty"] = hn_params.get("use_length_penalty", True)
                hn_filter_entry_stats["outlier_std"] = hn_params.get("outlier_std", 1.2)
                hn_filter_entry_stats["suspected_std"] = hn_params.get("suspected_std", 3.0)
                hn_filter_entry_stats["gamma"] = hn_params.get("gamma", 0.2)
            hn_filter_instance = HardNegativeFilter(hn_filter_entry_stats)

        logger.info("Processing: %s (replica=%d, chat_type=%s)", uri, entry.replica, entry.chat_type)

        raw_data = DataLoader.base_load(entry.dist_uri)
        logger.info("  Loaded %d raw samples", len(raw_data))

        template_fn = registry.get_template_fn(entry.chat_type)
        prompts = entry.system_prompt or []
        prompt_names = entry.system_prompt_name or []

        for rep in range(entry.replica):
            for row_idx, sample in enumerate(raw_data):
                
                #logger.info("Processing sample:"+str(sample))
                
                assigned = assigner.assign(sample, prompts, prompt_names, row_idx)
                for sample_copy, prompt_content, prompt_id in assigned:
                    try:
                        processed = template_fn(sample_copy, prompt_content, temperature=temperature, hn_filter=hn_filter_instance)
                        if processed is None:
                            #logger.info("  Dropped sample (hard negative filter): %s", sample_copy.get("_id_hash", ""))
                            dropped+=1
                            continue
                        processed["_source_uri"] = uri
                        processed["_replica"] = rep
                        processed["_system_prompt_id"] = prompt_id
                        # Include _id_hash from the original sample when available
                        processed["_id_hash"] = sample_copy.get("_id_hash", processed.get("_id_hash"))
                        all_samples.append(processed)
                    except (ValueError, KeyError) as e:
                        logger.warning("  Skipping sample: %s", e)
                        logger.debug("  Sample content: %s", json.dumps(sample_copy, ensure_ascii=False))

    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir 
    logger.info("Collected %d processed samples", len(all_samples))
    logger.info("Dropped %d samples", dropped)

    # ------------------------------------------------------------------
    # Post-processing: convert, filter, split, shuffle (in-memory)
    # ------------------------------------------------------------------
    import pandas as pd
    ds = Dataset.from_pandas(pd.DataFrame(data=all_samples))

    # Convert message-lists to plain strings
    def _format_message_list(msgs):
        if msgs is None:
            return ""
        parts = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            content = m.get("content", "")
            if content:
                parts.append(content)
        return "\n".join(parts)

    def _convert_example(example):
        try:
            example["prompt"] = _format_message_list(example.get("prompt", []))
            chosen = example.get("chosen", [])
            example["chosen"] = _format_message_list(chosen) if isinstance(chosen, list) else (chosen or "")
            rejected = example.get("rejected", [])
            example["rejected"] = _format_message_list(rejected) if isinstance(rejected, list) else (rejected or "")
        except Exception:
            pass
        return example

    ds = ds.map(_convert_example, batched=False)
    logger.info("Converted message-lists to strings")

    # Filter by token count
    filtered_samples = require_field(config, "model", "dataset", "filtered_samples", config_file=config_path)
    model_uri = require_field(config, "model", "model_uri", config_file=config_path)
    tokenizer = get_local_tokenizer(model_uri)
    MAX_PAIR_TOKENS = config.get("model", {}).get("dataset", {}).get("max_length", 4096)
    ds = filter_by_token(ds, tokenizer, filtered_samples, MAX_PAIR_TOKENS=MAX_PAIR_TOKENS)

    # Train/eval split
    eval_size = config.get("model", {}).get("training", {}).get("eval_size", 0.05)
    if eval_size and eval_size > 0:
        split = ds.train_test_split(test_size=eval_size)
        ds_train, ds_eval = split['train'], split['test']
    else:
        ds_train, ds_eval = ds, ds.select([])

    # Block shuffle (train only)
    dataset_cfg = config.get("model", {}).get("dataset", {})
    shuffle_strategy_str = dataset_cfg.get("shuffle_strategy")
    if shuffle_strategy_str:
        shuffle_block_size = dataset_cfg.get("shuffle_block_size", 1000)
        shuffle_seed = dataset_cfg.get("shuffle_seed", 42)
        strategy = ShuffleStrategy(shuffle_strategy_str.lower())
        shuffler = DatasetShuffler(strategy=strategy, block_size=shuffle_block_size, seed=shuffle_seed)
        ds_train = shuffler.shuffle(ds_train)
        logger.info("Applied %s block shuffle (block_size=%d)", strategy, shuffle_block_size)

    # Save final DatasetDict (train.py loads this directly)
    # Clean previous data to avoid orphan files
    if output_path.exists():
        shutil.rmtree(output_path)
        logger.info("Cleaned previous cache at %s", output_path)
    final = DatasetDict({'train': ds_train, 'test': ds_eval})
    final.save_to_disk(str(output_path))
    logger.info("Final dataset saved: %d train, %d eval -> %s", len(ds_train), len(ds_eval), output_path)

    return output_path


if __name__ == "__main__":
    config = sys.argv[1] if len(sys.argv) > 1 else "config.yml"
    prepare(config)
