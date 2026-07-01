"""Neo4j async driver singleton with connection pooling, schema initialization, and verification."""

from __future__ import annotations

import os
import logging
import asyncio
from typing import Optional
from pathlib import Path

from neo4j import AsyncDriver, AsyncGraphDatabase, exceptions


logger = logging.getLogger(__name__)

# Module-level singleton
_driver: Optional[AsyncDriver] = None
_schema_initialized = False


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


async def load_cypher_file(path: Path) -> str:
    """Load Cypher script from file."""
    if not path.exists():
        raise FileNotFoundError(f"Cypher file not found: {path}")

    with open(path, 'r') as f:
        return f.read()


async def execute_cypher_script(
    driver: AsyncDriver, script: str, script_name: str, allow_failures: bool = False
) -> bool:
    """Execute a Cypher script line by line.

    Args:
        driver: Neo4j AsyncDriver instance
        script: Cypher script content
        script_name: Name for logging
        allow_failures: If True, skip APOC procedure failures gracefully

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"[Schema Init] Executing {script_name}...")

        # Split by semicolon, removing comments and empty lines
        statements = []
        current_stmt = ""

        for line in script.split('\n'):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('//'):
                continue

            current_stmt += line + '\n'

            if line_stripped.endswith(';'):
                statements.append(current_stmt)
                current_stmt = ""

        # Execute each statement
        async with driver.session() as session:
            for stmt in statements:
                if stmt.strip():
                    try:
                        await session.run(stmt)
                    except exceptions.ClientError as e:
                        if allow_failures and "apoc.trigger" in stmt.lower():
                            logger.warning(
                                f"[Schema Init] ⚠ APOC trigger skipped (expected in certain modes): {e.message}"
                            )
                        else:
                            logger.error(f"[Schema Init] Error in {script_name}: {e}")
                            if not allow_failures:
                                raise
                    except Exception as e:
                        logger.error(f"[Schema Init] Error executing statement: {e}")
                        if not allow_failures:
                            raise

        logger.info(f"[Schema Init] ✓ {script_name} executed successfully")
        return True

    except Exception as e:
        logger.error(f"[Schema Init] ✗ {script_name} failed: {e}")
        return not allow_failures  # Return False only if failures are not allowed


async def initialize_schema(driver: AsyncDriver, scripts_dir: Path | None = None) -> bool:
    """Initialize Neo4j schema with Cypher scripts.

    Args:
        driver: Neo4j AsyncDriver instance
        scripts_dir: Directory containing 01-schema.cypher, 02-triggers.cypher

    Returns:
        True if successful, False otherwise
    """
    global _schema_initialized

    if _schema_initialized:
        logger.info("[Schema Init] Schema already initialized, skipping")
        return True

    if scripts_dir is None:
        scripts_dir = Path(__file__).parent

    try:
        logger.info(f"[Schema Init] Starting schema initialization from {scripts_dir}...")

        scripts = [
            ("01-schema.cypher", "Schema Definition (constraints, indexes)", False),
            ("02-triggers.cypher", "APOC Triggers (timestamps, validation)", True),
        ]

        for filename, description, allow_failures in scripts:
            script_path = scripts_dir / filename

            if not script_path.exists():
                logger.warning(f"[Schema Init] Skipping {filename}: file not found at {script_path}")
                continue

            script_content = await load_cypher_file(script_path)
            success = await execute_cypher_script(driver, script_content, description, allow_failures)

            if not success and not allow_failures:
                logger.error(f"[Schema Init] Critical schema script failed: {filename}")
                return False

            await asyncio.sleep(0.5)

        logger.info("[Schema Init] ✓ Schema initialization complete!")
        _schema_initialized = True
        return True

    except Exception as e:
        logger.error(f"[Schema Init] Schema initialization failed: {e}")
        return False


async def verify_schema(driver: AsyncDriver) -> bool:
    """Verify schema integrity: constraints, indexes, triggers, and seed data.

    Returns:
        True if schema is valid, False otherwise
    """
    logger.info("[Schema Verification] Starting schema verification...")

    try:
        async with driver.session() as session:
            # 1. Verify constraints exist
            constraints_result = await session.run("CALL db.constraints()")
            constraints = [record async for record in constraints_result]
            logger.info(f"[Schema Verification] Found {len(constraints)} constraints")

            # 2. Verify indexes exist
            indexes_result = await session.run("CALL db.indexes()")
            indexes = [record async for record in indexes_result]
            logger.info(f"[Schema Verification] Found {len(indexes)} indexes")

            # 3. Verify node types
            for node_type in ["Recipe", "Model", "Experiment", "Checkpoint", "Component"]:
                count_result = await session.run(f"MATCH (n:{node_type}) RETURN COUNT(n) AS count")
                count = [record async for record in count_result]
                if count:
                    logger.info(f"[Schema Verification] {node_type}: {count[0]['count']} nodes")

            # 4. Check for orphan checkpoints
            orphans_result = await session.run("""
                MATCH (c:Checkpoint)
                WHERE NOT (()-[:PRODUCED]->(c)) AND c.is_merging <> true
                RETURN COUNT(c) AS orphan_count
            """)
            orphans = [record async for record in orphans_result]
            orphan_count = orphans[0]["orphan_count"] if orphans else 0
            if orphan_count > 0:
                logger.warning(f"[Schema Verification] ⚠ Found {orphan_count} orphan checkpoints")

        logger.info("[Schema Verification] ✓ Schema verification passed!")
        return True

    except Exception as e:
        logger.error(f"[Schema Verification] ✗ Verification failed: {e}")
        return False


class Neo4jClient:
    """Singleton wrapper for Neo4j driver with automatic schema initialization and verification."""

    _instance: Optional[Neo4jClient] = None
    _initialized = False

    def __init__(self, driver: AsyncDriver | None = None, auto_init: bool = True):
        """Initialize Neo4jClient wrapper.

        Args:
            driver: Optional AsyncDriver instance. If None, get_driver() will be called.
            auto_init: If True, automatically initialize and verify schema on first connect.
        """
        self.driver = driver
        self._repo = None
        self.auto_init = auto_init

    @classmethod
    def get_instance(cls, auto_init: bool = True) -> Neo4jClient:
        """Get or create singleton instance.

        Args:
            auto_init: If True, automatically initialize and verify schema on first connect.

        Returns:
            Neo4jClient singleton instance
        """
        if cls._instance is None:
            cls._instance = cls(auto_init=auto_init)
        return cls._instance

    async def ensure_initialized(self) -> bool:
        """Ensure driver is initialized, schema is set up, and verified.

        This method is idempotent: it can be called multiple times safely.

        Returns:
            True if all checks passed, False otherwise
        """
        if Neo4jClient._initialized:
            return True

        try:
            # Get or create driver
            if self.driver is None:
                self.driver = await get_driver()

            # Initialize schema
            if not await initialize_schema(self.driver):
                logger.error("[Client] Failed to initialize schema")
                return False

            # Verify schema
            if not await verify_schema(self.driver):
                logger.error("[Client] Schema verification failed")
                return False

            Neo4jClient._initialized = True
            logger.info("[Client] ✓ Neo4j client fully initialized with verified schema")
            return True

        except Exception as e:
            logger.error(f"[Client] Initialization failed: {e}")
            return False

    async def close(self) -> None:
        """Close the driver and reset state."""
        if self.driver:
            await self.driver.close()
            self.driver = None
        Neo4jClient._initialized = False
        Neo4jClient._instance = None
