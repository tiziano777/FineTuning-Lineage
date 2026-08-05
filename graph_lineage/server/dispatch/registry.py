"""HandlerRegistry: storage and lookup of RunCaseHandler instances.

Ogni handler e' indicizzato per (domain, run_type). La registry non
conosce euristiche di rilevamento del dominio: quella logica vive in
DomainDispatcher (domain_dispatcher.py).
"""
from __future__ import annotations

from fastapi import HTTPException
from graph_lineage.server.handlers.run_case_handler import RunCaseHandler
from graph_lineage.server.handlers.training_run_case_handler import TrainingRunHandler

class HandlerRegistry:
    """Contenitore di RunCaseHandler, raggruppati per Actor-Domain."""

    def __init__(self):
        self._handlers: dict[str, dict[str, RunCaseHandler]] = {}
        self.register("training", TrainingRunHandler())

    def register(self, domain: str, handler: RunCaseHandler) -> None:
        """Registra un handler per il suo run_type all'interno di un dominio."""
        self._handlers.setdefault(domain, {})[handler.user_domain] = handler

    def get(self, domain: str, run_type: str) -> RunCaseHandler:
        """Recupera l'handler per (domain, run_type).

        Raises:
            HTTPException: 422 se il dominio o il run_type non sono supportati.
        """
        handler = self._handlers.get(domain, {}).get(run_type)
        if handler is None:
            raise HTTPException(
                status_code=422,
                detail=f"Domain '{domain}': unsupported run_type '{run_type}'",
            )
        return handler

    def has_domain(self, domain: str) -> bool:
        return domain in self._handlers

    def domains(self) -> list[str]:
        return list(self._handlers.keys())

    def list(self) -> dict[str, list[str]]:
        """Elenca i run_type registrati, per dominio."""
        return {d: list(handlers.keys()) for d, handlers in self._handlers.items()}
