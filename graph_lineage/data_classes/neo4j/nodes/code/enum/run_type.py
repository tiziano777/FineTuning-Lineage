from enum import Enum

class RunType(str, Enum):
    """Tipo di run base."""
    CODE = "code"
    TRAINING = "training"
    EVALUATION = "evaluation"
    INFERENCE = "inference"
    MERGING = "merging"
    
    @classmethod
    def from_string(cls, value: str):
        """Converte una stringa in un valore enum valido."""
        try:
            return cls(value)
        except ValueError:
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
            raise ValueError(f"'{value}' is not a valid RunType")