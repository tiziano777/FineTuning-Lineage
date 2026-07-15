from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Any
import json

class GenericNode(BaseModel):
    """Modello per leggere un nodo generico da Neo4j.

    Deserializza automaticamente il payload JSON string in dict.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra='allow',  # Permette campi extra dal nodo Neo4j
    )

    id: str
    type: str
    payload_json: str = Field(alias="payload")  # Neo4j ha il campo "payload" (JSON string)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator('payload_json', mode='before')
    @classmethod
    def parse_payload(cls, v):
        """Se il payload è già un dict (es. da Pydantic), lascialo.
        Se è una stringa JSON, deserializzala."""
        if isinstance(v, dict):
            return json.dumps(v)  # Re-serializza per coerenza
        if isinstance(v, str):
            # Verifica che sia JSON valido
            try:
                json.loads(v)
                return v
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON in payload: {v[:100]}")
        raise ValueError(f"Payload must be dict or JSON string, got {type(v)}")

    @property
    def payload(self) -> dict[str, Any]:
        """Ritorna il payload come dict Python (deserializzato)."""
        return json.loads(self.payload_json)

    @field_validator('created_at', mode='before')
    @classmethod
    def convert_neo4j_datetime(cls, v):
        """Convert neo4j.time.DateTime to Python datetime."""
        if hasattr(v, 'to_native') and callable(v.to_native):
            return v.to_native()
        return v
