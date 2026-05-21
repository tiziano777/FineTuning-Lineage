"""Scope enumeration for fine-tuning recipes."""

from enum import Enum


class ScopeEnum(str, Enum):
    """Valid scopes for fine-tuning recipes."""

    SFT = "sft"
    PREFERENCE = "preference"
    REWARD_MODEL = "reward_model"
    EVALUATION = "evaluation"
    UNKNOWN = "unknown"

    @classmethod
    def values(cls) -> list[str]:
        """Return list of all scope values."""
        return [scope.value for scope in cls]
