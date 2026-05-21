"""Health check utilities for Streamlit UI."""

from __future__ import annotations

import httpx

from graph_lineage.streamlit_ui.db.neo4j_async import AsyncNeo4jClient


async def check_neo4j_health(client: AsyncNeo4jClient) -> bool:
    """Check Neo4j connection health.

    Args:
        client: AsyncNeo4jClient instance.

    Returns:
        True if healthy, False otherwise.
    """
    try:
        result = await client.run_single("RETURN 1 as status")
        return result is not None
    except Exception:
        return False


async def check_master_api_health(base_url: str, token: str = "") -> bool:
    """Check Master API health endpoint.

    Args:
        base_url: Master API base URL.
        token: API token.

    Returns:
        True if healthy, False otherwise.
    """
    try:
        async with httpx.AsyncClient() as client:
            headers = {"X-API-Key": token} if token else {}
            response = await client.get(f"{base_url}/health", headers=headers)
            return response.status_code == 200
    except Exception:
        return False


def check_streamlit_health() -> bool:
    """Check Streamlit health (always True if running).

    Returns:
        True (Streamlit is running if this executes).
    """
    return True
