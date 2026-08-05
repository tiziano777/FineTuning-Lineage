"""DomainDispatcher: rileva il dominio di una request e risolve l'handler.

Il dominio identifica la "famiglia" di handler da usare (es. "ai" per il
training, "generic" per domini futuri). Lo storage degli handler vive in
HandlerRegistry (registry.py); questo modulo si occupa solo delle
euristiche di rilevamento.
"""
from __future__ import annotations
from fastapi import HTTPException
from graph_lineage.server.handlers.run_case_handler import RunCaseHandler
from graph_lineage.server.dispatch.registry import HandlerRegistry

class DomainDispatcher:
    """Rileva il dominio di una request e ne risolve l'handler tramite una HandlerRegistry.

    Euristiche di rilevamento (in ordine di priorità):
    1. Campo esplicito `domain` sulla request → usa quel dominio.
    2. Campi AI-specifici presenti (model_id, recipe_id, component_id) → dominio "ai".
    3. Fallback → dominio "generic".
    """

    def __init__(self, registry: HandlerRegistry):
        self._registry = registry

    def resolve_handler(self, request) -> RunCaseHandler:
        """Rileva il dominio dalla request e ritorna l'handler per il suo run_type.

        Raises:
            HTTPException: 422 se il dominio o il run_type non sono supportati.
        """
        domain = self._detect_domain(request)
        if not self._registry.has_domain(domain):
            raise HTTPException(
                status_code=422,
                detail=f"Domain '{domain}' not registered. Available: {self._registry.domains()}",
            )
        return self._registry.get(domain, request.user_domain)

    def _detect_domain(self, request) -> str:
        explicit_domain = getattr(request, "user_domain")
        if explicit_domain and self._registry.has_domain(explicit_domain):
            return explicit_domain

        return "generic"
