from datetime import datetime
import uuid
from pydantic import BaseModel, Field, field_validator

class BaseEntity(BaseModel):
    """Base for all Neo4j node types with shared fields."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="UUID primary key")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @field_validator('created_at', 'updated_at', mode='before')
    @classmethod
    def convert_neo4j_datetime(cls, v):
        """Convert neo4j.time.DateTime to Python datetime."""
        # Se è un oggetto Neo4j DateTime, convertilo
        if hasattr(v, 'to_native') and callable(v.to_native):
            return v.to_native()
        return v