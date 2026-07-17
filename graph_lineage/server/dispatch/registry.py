"""Registry and dispatch for RunTypeHandler implementations.

Wrappa il registry esistente in un DomainDispatcher a due livelli.
aggiunge il livello di dominio richiesto dal refactor.
"""

from __future__ import annotations

from graph_lineage.server.dispatch.domain_dispatcher import DomainDispatcher
from graph_lineage.server.handlers.base import RunTypeHandler
from graph_lineage.server.handlers.training_run_handler import TrainingRunHandler

# ── Backward-compat: registry singolo-livello (AI domain) ───────────────

_HANDLERS: dict[str, RunTypeHandler] = {}


def register_handler(handler: RunTypeHandler) -> None:
    """Register a RunTypeHandler for its run_type (backward-compat, dominio AI)."""
    _HANDLERS[handler.run_type] = handler


def get_handler(run_type: str) -> RunTypeHandler:
    """Retrieve the handler for a given run_type (backward-compat, dominio AI).

    Raises:
        HTTPException: 422 if the run_type is not supported.
    """
    handler = _HANDLERS.get(run_type)
    if handler is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Unsupported run_type '{run_type}'")
    return handler


# Auto-register built-in handlers (backward-compat)
register_handler(TrainingRunHandler())


# ── Nuovo: DomainDispatcher a due livelli ───────────────────────────────

# Istanza singleton del dispatcher di dominio
domain_dispatcher = DomainDispatcher()

# Registra il dominio AI con i suoi handler
domain_dispatcher.register_domain_handler("ai", TrainingRunHandler())


# Nuove API per il dispatch di dominio
def resolve_handler(request) -> RunTypeHandler:
    """Risolve l'handler dalla request usando il DomainDispatcher.

    Euristiche:
    1. Campo esplicito `domain` nella request
    2. Campi AI-specifici (model_id, recipe_id, component_id) → dominio "ai"
    3. Fallback → dominio "generic"

    Args:
        request: PreRequest o oggetto con attributi run_type, domain, model_id, etc.

    Returns:
        RunTypeHandler appropriato per il dominio e run_type rilevati.
    """
    return domain_dispatcher.resolve(request)

def register_domain_handler(domain: str, handler: RunTypeHandler) -> None:
    """Registra un handler in un dominio specifico.

    Usage per futuri plugin:
        from graph_lineage.server.dispatch.registry import register_domain_handler
        register_domain_handler("generic", DocumentRunHandler())
    """
    domain_dispatcher.register_domain_handler(domain, handler)

def list_domains() -> list[str]:
    """Elenca i domini registrati."""
    return domain_dispatcher.list_domains()

def list_run_types(domain: str | None = None) -> dict[str, list[str]]:
    """Elenca i run_type per dominio."""
    return domain_dispatcher.list_run_types(domain)

