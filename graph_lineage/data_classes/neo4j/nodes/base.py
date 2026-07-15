from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Dict, Any

class BaseEntity(BaseModel):
    """Base for all Neo4j node types with shared fields."""

    # Abilita il framework ad accettare campi extra non definiti
    model_config = ConfigDict(extra='allow')

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="UUID primary key")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last update timestamp")

    @field_validator('created_at', 'updated_at', mode='before')
    @classmethod
    def convert_neo4j_datetime(cls, v):
        """Convert neo4j.time.DateTime to Python datetime."""
        if hasattr(v, 'to_native') and callable(v.to_native):
            return v.to_native()
        return v
    
    @property
    def custom_fields(self) -> Dict[str, Any]:
        """Estrae i campi extra non definiti nel modello usando le feature native di Pydantic v2."""
        return self.model_extra or {}

