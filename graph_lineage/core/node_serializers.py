"""Node serializer registry.

Permette ai plugin di dominio di registrare logica custom di serializzazione
per tipi di nodo specifici, senza contaminare il core.

Sostituisce l'`if node_type == "Checkpoint"` hardcoded in generic_node_ops.py.
"""

from __future__ import annotations
from typing import Any, Callable

# Registry globale: node_type -> serializer function
_NODE_SERIALIZERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

def register_node_serializer(
    node_type: str,
    serializer: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """Registra un serializzatore per un tipo di nodo.

    Il serializzatore riceve il payload dict e ritorna le proprietà flat
    da scrivere direttamente sul nodo Neo4j.

    Args:
        node_type: Il tipo di nodo (es. "Checkpoint", "Metric", "Artifact")
        serializer: Funzione dict -> dict che trasforma il payload.

    Esempio (nel plugin AI):
        def checkpoint_serializer(payload: dict) -> dict:
            return {
                "name": payload.get("name", ""),
                "derived_from": payload.get("derived_from", ""),
                "epoch": payload.get("epoch", 0),
                "run": payload.get("run", 0),
                "uri": payload.get("uri", ""),
                "metrics": payload.get("metrics", ""),
                "is_merging": payload.get("is_merging", False),
            }

        register_node_serializer("Checkpoint", checkpoint_serializer)
    """
    _NODE_SERIALIZERS[node_type] = serializer

def get_node_serializer(
    node_type: str,
) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    """Ritorna il serializzatore registrato per il tipo, o None se non esiste."""
    return _NODE_SERIALIZERS.get(node_type)

def serialize_node_payload(node_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Applica il serializzatore registrato per il tipo, o ritorna il payload as-is.

    Usato da create_generic_graph_node per decidere se flattenare proprietà
    o mantenerle nested nel campo `payload`.
    """
    serializer = _NODE_SERIALIZERS.get(node_type)
    if serializer:
        return serializer(payload)
    return payload

def has_custom_serializer(node_type: str) -> bool:
    """True se esiste un serializzatore custom per questo tipo di nodo."""
    return node_type in _NODE_SERIALIZERS
