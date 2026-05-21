"""Async helper for running coroutines safely from Streamlit sync context."""

from __future__ import annotations

import asyncio

import nest_asyncio

nest_asyncio.apply()


def run_async(coro):
    """Run async coroutine safely from Streamlit sync context.

    Uses nest_asyncio to allow nested event loops, avoiding the
    RuntimeError that occurs when asyncio.run() is called inside
    an already-running event loop (common in Streamlit).
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
