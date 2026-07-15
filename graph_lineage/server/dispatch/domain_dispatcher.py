"""Two-level dispatch: Domain → RunTypeHandler.

Livello 1: risolve il dominio (AI vs generic vs futuri)
Livello 2: dispatch per run_type all'interno del dominio

Mantiene il registry esistente (`register_handler`/`get_handler`) invariato,
ma lo wrappa in un livello superiore di dominio.
"""

from __future__ import annotations

from fastapi import HTTPException

from graph_lineage.server.handlers.base import RunTypeHandler


class DomainRegistry:
    """Registry di handler per un singolo dominio."""

    def __init__(self, name: str):
        self.name = name
        self._handlers: dict[str, RunTypeHandler] = {}

    def register(self, handler: RunTypeHandler) -> None:
        """Registra un handler per il suo run_type all'interno di questo dominio."""
        self._handlers[handler.run_type] = handler

    def get_handler(self, run_type: str) -> RunTypeHandler:
        """Recupera l'handler per un dato run_type.

        Raises:
            HTTPException: 422 se il run_type non è supportato in questo dominio.
        """
        handler = self._handlers.get(run_type)
        if handler is None:
            raise HTTPException(
                status_code=422,
                detail=f"Domain '{self.name}': unsupported run_type '{run_type}'",
            )
        return handler

    def list_run_types(self) -> list[str]:
        """Elenca i run_type registrati in questo dominio."""
        return list(self._handlers.keys())


class DomainDispatcher:
    """Dispatcher a due livelli per risolvere il dominio e poi il run_type.

    Usage:
        dispatcher = DomainDispatcher()
        # Registrazione plugin AI (backward compat)
        from graph_lineage.server.handlers.training import TrainingRunHandler
        dispatcher.register_domain_handler("ai", TrainingRunHandler())

        # Registrazione futuro dominio generico
        dispatcher.register_domain_handler("generic", DocumentRunHandler())

        # Risoluzione
        handler = dispatcher.resolve(request)  # PreRequest
    """

    def __init__(self):
        self._domains: dict[str, DomainRegistry] = {}

    def register_domain(self, name: str, registry: DomainRegistry) -> None:
        """Registra un intero DomainRegistry."""
        self._domains[name] = registry

    def register_domain_handler(self, domain: str, handler: RunTypeHandler) -> None:
        """Registra un singolo handler in un dominio (crea il registry se manca)."""
        if domain not in self._domains:
            self._domains[domain] = DomainRegistry(name=domain)
        self._domains[domain].register(handler)

    def resolve(self, request) -> RunTypeHandler:
        """Risolve il dominio dalla request e ritorna l'handler appropriato.

        Euristiche di risoluzione (in ordine di priorità):
        1. Campo esplicito `domain` nella request → usa quel dominio
        2. Campi AI-specifici presenti (model_id, recipe_id, component_id) → dominio "ai"
        3. Fallback → dominio "generic" (sicuro, non assume AI)

        Args:
            request: PreRequest o qualsiasi oggetto con attributi
                     `run_type`, opzionalmente `domain`, `model_id`, `recipe_id`, `component_id`

        Returns:
            RunTypeHandler per il run_type risolto.

        Raises:
            HTTPException: 422 se il dominio o il run_type non sono supportati.
        """
        domain = self._detect_domain(request)
        registry = self._domains.get(domain)
        if registry is None:
            available = list(self._domains.keys())
            raise HTTPException(
                status_code=422,
                detail=f"Domain '{domain}' not registered. Available: {available}",
            )
        return registry.get_handler(request.run_type)

    def _detect_domain(self, request) -> str:
        """Euristiche per determinare il dominio dalla request."""
        # 1. Campo esplicito
        explicit_domain = getattr(request, "domain", None)
        if explicit_domain and explicit_domain in self._domains:
            return explicit_domain

        # 2. Euristiche AI: se presenti campi specifici del dominio training
        has_model = bool(getattr(request, "model_id", None))
        has_recipe = bool(getattr(request, "recipe_id", None))
        has_component = bool(getattr(request, "component_id", None))
        if has_model or has_recipe or has_component:
            return "ai"

        # 3. Fallback safe: generic
        return "generic"

    def list_domains(self) -> list[str]:
        """Elenca i domini registrati."""
        return list(self._domains.keys())

    def list_run_types(self, domain: str | None = None) -> dict[str, list[str]]:
        """Elenca i run_type per dominio. Se domain=None, tutti i domini."""
        if domain:
            reg = self._domains.get(domain)
            return {domain: reg.list_run_types()} if reg else {}
        return {name: reg.list_run_types() for name, reg in self._domains.items()}