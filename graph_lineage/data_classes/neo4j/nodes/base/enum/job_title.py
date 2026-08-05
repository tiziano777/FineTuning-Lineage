from enum import Enum

class JobTitle(str, Enum):
    """Ruolo di un attore in un run (convenzione Git)."""
    AI_ENGINEER = "ai_engineer"
    DATA_SCIENTIST = "data_scientist"
    DATA_ENGINEER = "data_engineer"
    DEVOPS_ENGINEER = "devops_engineer"
    SW_ENGINEER = "sw_engineer"
    DEVELOPER = "developer"
    SECURITY_ENGINEER = "security_engineer"
    PRODUCT_MANAGER = "product_manager"
    HR_MANAGER = "hr_manager"
    COMPLIANCE_OFFICER = "compliance_officer"
    COMPUTATIONAL_LINGUIST = "computational_linguist"
    PROJECT_MANAGER = "project_manager"

    @classmethod
    def from_string(cls, value: str):
        try:
            return cls(value)
        except ValueError:
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
            raise ValueError(f"'{value}' non è un valore valido per {cls.__name__}")
