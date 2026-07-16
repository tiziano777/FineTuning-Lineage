# generic node that extends BaseNode and can be used as extension for event Nodes.
from pydantic import Field, field_validator
from typing import Any
import json
from .base import BaseNode

# Useful to extend custom node with event emit fn, of custom nodes
class Event(BaseNode):
    """Modello per leggere un nodo generico da Neo4j.

    Deserializza automaticamente il payload JSON string in dict.
    """

    type: str
    payload_json: str = Field(alias="payload")  # Neo4j ha il campo "payload" (JSON string)

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
