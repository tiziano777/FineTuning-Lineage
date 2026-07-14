"""Registry and dispatch for RunTypeHandler implementations."""

from __future__ import annotations

from fastapi import HTTPException

from .base import RunTypeHandler
from .training import TrainingRunHandler

_HANDLERS: dict[str, RunTypeHandler] = {}

def register_handler(handler: RunTypeHandler) -> None:
    """Register a RunTypeHandler for its run_type."""
    _HANDLERS[handler.run_type] = handler

def get_handler(run_type: str) -> RunTypeHandler:
    """Retrieve the handler for a given run_type.

    Raises:
        HTTPException: 422 if the run_type is not supported.
    """
    handler = _HANDLERS.get(run_type)
    if handler is None:
        raise HTTPException(status_code=422, detail=f"Unsupported run_type '{run_type}'")
    return handler

# Auto-register built-in handlers
register_handler(TrainingRunHandler())