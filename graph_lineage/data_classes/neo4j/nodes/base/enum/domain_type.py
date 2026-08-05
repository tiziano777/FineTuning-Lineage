from enum import Enum

class DomainType(str, Enum):
    """Metodi o utilità comuni a tutti i domini."""
    
    @classmethod
    def from_string(cls, value: str):
        try:
            return cls(value)
        except ValueError:
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
            raise ValueError(f"'{value}' non è un valore valido per {cls.__name__}")