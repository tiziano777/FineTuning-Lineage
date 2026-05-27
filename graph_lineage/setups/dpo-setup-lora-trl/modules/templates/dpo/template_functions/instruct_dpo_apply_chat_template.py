"""Chat template function for chat_type: train_dpo.

Preprocesses a DPO input sample (following input_schema.json) into the
format required by trl.DPOTrainer:

    {"prompt": [messages...], "chosen": [messages...], "rejected": [messages...]}

Each value is a list of {"role": str, "content": str} dicts.

Selection logic for the generation turn (ASSISTANT with positives/negatives):
  - From `positives`, pick the inference_item matching `temperature`.
  - From `negatives`, pick the inference_item matching `temperature`.
  - If no exact temperature match, pick the first item as fallback.

Multi-turn: completed ASSISTANT turns (those with `content`) are kept as
context in the prompt prefix. The final ASSISTANT turn (with positives/negatives)
is the generation target — its content goes into chosen/rejected.
"""

from __future__ import annotations

from modules.filters.hard_negative_filtering import HardNegativeFilter


def _select_by_temperature(items: list[dict], temperature: float) -> dict:
    """Pick the inference_item whose inference_params.temperature matches."""
    for item in items:
        params = item.get("inference_params") or {}
        if params.get("temperature") == temperature:
            return item
    # Fallback: first item
    return items[0] if items else {}


def _extract_content(item: dict) -> str:
    """Get displayable content from an inference_item."""
    return item.get("content") or ""


def apply_chat_template(
    sample: dict,
    system_prompt: str | None,
    temperature: float = 0.7,
    hn_filter: HardNegativeFilter | None = None,
) -> dict | None:
    """Convert a raw DPO sample into DPOTrainer-compatible format.

    Args:
        sample:        Raw sample dict following input_schema.json.
        system_prompt: Injected as first system message if provided.
        temperature:   Select positive/negative by this temperature value.
        hn_filter:     Optional HardNegativeFilter for NLP-based rejected selection.

    Returns:
        {"prompt": [...], "chosen": [...], "rejected": [...]}
        Each is a list of {"role": str, "content": str} message dicts.
        Returns None if the sample should be dropped (hard negative filter decision).

    Raises:
        ValueError: on missing/malformed data.
    """
    id_hash: str = sample.get("_id_hash", "<unknown>")
    raw_messages = sample.get("messages", [])

    # Be explicit about emptiness checks: samples may contain numpy arrays or
    # pandas Series where truthiness raises ValueError. Use len() when available.
    if raw_messages is None:
        raise ValueError(f"Sample {id_hash}: 'messages' is missing or empty.")
    if hasattr(raw_messages, "__len__"):
        if len(raw_messages) == 0:
            raise ValueError(f"Sample {id_hash}: 'messages' is missing or empty.")
    else:
        # Non-iterable / unexpected type
        raise ValueError(f"Sample {id_hash}: 'messages' is not an iterable of messages.")

    prompt_messages: list[dict] = []

    if system_prompt:
        prompt_messages.append({"role": "system", "content": system_prompt})

    chosen_content: str | None = None
    rejected_content: str | None = None

    for msg in raw_messages:
        role: str = (msg.get("role") or "").upper()

        if role == "USER":
            content = msg.get("content", "")
            if not content:
                raise ValueError(f"Sample {id_hash}: USER message has empty 'content'.")
            prompt_messages.append({"role": "user", "content": content})

        elif role == "ASSISTANT":
            # Generation target turn — extract chosen/rejected
            positives = msg.get("positives", [])
            negatives = msg.get("negatives", [])

            if not positives:
                raise ValueError(f"Sample {id_hash}: generation turn has no positives.")
            if not negatives:
                raise ValueError(f"Sample {id_hash}: generation turn has no negatives.")

            chosen_item = _select_by_temperature(positives, temperature)
            chosen_content = _extract_content(chosen_item)

            # Hard negative selection: NLP-based or temperature fallback
            if hn_filter:
                rejected_item = hn_filter.select(
                    negatives, gold_content=chosen_content, temperature=temperature
                )
                if rejected_item is None:
                    return None  # signal drop to caller
            else:
                rejected_item = _select_by_temperature(negatives, temperature)

            rejected_content = _extract_content(rejected_item)
        else:
            raise ValueError(f"Sample {id_hash}: unexpected role '{role}'.")

    if chosen_content is None or rejected_content is None:
        raise ValueError(f"Sample {id_hash}: no generation turn with positives/negatives found.")

    # The last prompt message before generation should be a user turn
    non_system = [m for m in prompt_messages if m["role"] != "system"]
    if not non_system or non_system[-1]["role"] != "user":
        raise ValueError(f"Sample {id_hash}: last prompt message must be a user turn.")

    return {
        "prompt": prompt_messages,
        "chosen": [{"role": "assistant", "content": chosen_content}],
        "rejected": [{"role": "assistant", "content": rejected_content}],
    }
