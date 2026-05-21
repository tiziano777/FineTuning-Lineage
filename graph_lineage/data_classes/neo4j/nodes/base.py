from datetime import datetime
import uuid
from pydantic import BaseModel, Field

class BaseEntity(BaseModel):
    """Base for all Neo4j node types with shared fields."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="UUID primary key")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")
