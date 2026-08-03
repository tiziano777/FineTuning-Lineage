# generic node that extends BaseNode and can be used as extension for event Nodes.
from pydantic import Field, field_validator
from typing import Any, Dict, Optional
import json
from pydantic import  ConfigDict
from .base import BaseNode

class Event(BaseNode):
    """ 
    Definizione DataObject prodotta da un Case Execution durante esecuzione (ACM Case Event).
    Questo DataObject è un oggetto generico che è usato per gestire eventi dal EventHandler(e: Event), e può essere esteso con campi custom.
        
    Può:
    1) essere esteso con relativo custom edge + produced Artifact node. (current_run_id, edge_type, edge_payload_json, node_type, node_payload_json)
    2) Se event non produce output, può essere usato come nodo generico senza edge e senza Artifact node. (current_run_id)
    3) Oppure Se event produce un update del current case, invocare update sul current CaRun(Case). (current_run_id, update_payload_json)
    """

    # Abilita il framework ad accettare campi extra non definiti
    model_config = ConfigDict(extra='allow')

    current_run_id: str = Field(description="Identificatore del Run(Case) corrente")
    update_payload_json: Optional[Dict[str, Any]] = Field(description="update payload JSON")

    edge_type: Optional[str] = Field(description="edge type")
    edge_payload_json: Optional[Dict[str, Any]] = Field(description="edge payload JSON")

    node_type: Optional[str] = Field(description="node type")  
    node_payload_json: Optional[Dict[str, Any]] = Field(description="node payload JSON")

    @field_validator('edge_payload_json', 'node_payload_json', mode='before')
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
    def node_payload(self) -> dict[str, Any]:
        """Ritorna il payload come dict Python (deserializzato)."""
        return json.loads(self.node_payload_json)

    @property
    def edge_payload(self) -> dict[str, Any]:
        """Ritorna il payload come dict Python (deserializzato)."""
        return json.loads(self.edge_payload_json)

