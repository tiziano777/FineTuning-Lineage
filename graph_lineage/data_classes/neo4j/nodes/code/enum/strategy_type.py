from enum import Enum

class StrategyType(str, Enum):
    NEW = "NEW"
    RESUME = "RESUME"
    BRANCH = "BRANCH"
    RETRY = "RETRY"

    @classmethod
    def from_string(cls, value: str):
        """Converte una stringa in un valore enum valido."""
        try:
            return cls(value)
        except ValueError:
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
            raise ValueError(f"'{value}' is not a valid StrategyType")