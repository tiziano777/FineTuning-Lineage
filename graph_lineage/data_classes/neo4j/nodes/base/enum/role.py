from enum import Enum

class Role(str, Enum):
    """Responsabilità di un attore in un Case/project specifico (convenzione Git)."""
    OWNER = "owner"
    MAINTAINER = "maintainer"
    EDITOR = "editor"
    VIEWER = "viewer"

    @classmethod
    def from_string(cls, value: str):
        try:
            return cls(value)
        except ValueError:
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
            raise ValueError(f"'{value}' non è un valore valido per {cls.__name__}")