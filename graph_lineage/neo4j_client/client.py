"""Neo4j async driver singleton with connection pooling for lineage tracking."""

from __future__ import annotations

import os
from typing import Optional

from neo4j import AsyncDriver, AsyncGraphDatabase


# Module-level singleton
_driver: Optional[AsyncDriver] = None


async def get_driver(reinit: bool = False) -> AsyncDriver:
    """Get or create the Neo4j driver singleton.

    Args:
        reinit: If True, close existing driver and create a new one.

    Returns:
        AsyncDriver instance for Neo4j 5.x async operations.
    """
    global _driver

    if reinit and _driver is not None:
        await close_driver()

    if _driver is None:
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        pool_size = int(os.getenv("NEO4J_POOL_SIZE", "50"))

        _driver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=pool_size,
        )

    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver and reset singleton."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


class Neo4jClient:
    """Singleton wrapper for Neo4j driver and repository access."""

    _instance: Optional[Neo4jClient] = None
    _repository: Optional[object] = None

    def __init__(self, driver: AsyncDriver | None = None):
        """Initialize Neo4jClient wrapper.

        Args:
            driver: Optional AsyncDriver instance. If None, get_driver() will be called.
        """
        self.driver = driver
        self._repo = None

    @classmethod
    def get_instance(cls) -> Neo4jClient:
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def repository(self):
        """Lazy-load repository from neo4j_client.repository."""
        if self._repo is None:
            from neo4j_client.repository import ExperimentRepositoryAsync

            self._repo = ExperimentRepositoryAsync(self.driver)
        return self._repo
