from __future__ import annotations

import os
import logging
import asyncio
from typing import Any, Optional
from pathlib import Path

# Usiamo tenacity per rendere i controlli di inizializzazione indistruttibili
from tenacity import retry, stop_after_attempt, wait_exponential
from neo4j import AsyncDriver, AsyncGraphDatabase, exceptions

logger = logging.getLogger(__name__)

class Neo4jClient:
    """Base client. All queries are consumed fully before releasing the driver."""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        pool_size: int = 50,
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.pool_size = pool_size

    async def get_driver(self) -> AsyncDriver:
        raise NotImplementedError

    async def close_driver(self, driver: AsyncDriver) -> None:
        raise NotImplementedError

    async def run(self, query: str, **kwargs: Any) -> list[dict]:
        """Execute query safely using Neo4j transaction auto-retry under the hood."""
        driver = await self.get_driver()
        try:
            async with driver.session() as session:
                # La letteratura Neo4j consiglia di usare le transaction unit (execute_read/write).
                # Qui usiamo un approccio generico resiliente.
                async def _work(tx):
                    result = await tx.run(query, **kwargs)
                    return [dict(r) async for r in result]
                
                # Scegliamo se è read o write in base alla query (euristica semplice)
                is_write = any(x in query.upper() for x in ["CREATE", "MERGE", "SET", "DELETE", "REMOVE"])
                if is_write:
                    return await session.execute_write(_work)
                else:
                    return await session.execute_read(_work)
        finally:
            await self.close_driver(driver)

    async def run_single(self, query: str, **kwargs: Any) -> Optional[dict]:
        records = await self.run(query, **kwargs)
        return records[0] if records else None

    async def run_list(self, query: str, **kwargs: Any) -> list[dict]:
        return await self.run(query, **kwargs)

    async def query(self, query: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        return await self.run_list(query, **params)

    async def count_relationships(self, node_id: str, label: str) -> int:
        ALLOWED = {"Model", "Component", "Recipe"}
        if label not in ALLOWED:
            raise ValueError(f"Invalid label: {label}. Allowed: {ALLOWED}")
        
        # Sicuro da Cypher injection grazie alla whitelist rigida
        query = f"""
            MATCH (n:{label} {{id: $id}})<-[r]-(m)
            RETURN count(r) AS dep_count
        """
        records = await self.run(query, id=node_id)
        return records[0]["dep_count"] if records else 0

    async def close(self) -> None:
        pass


# ───────────────────────────────────────────────
# 1. Backend / CLI — Persistent Version
# ───────────────────────────────────────────────

class PersistentNeo4jClient(Neo4jClient):
    """Singleton driver with pooling, schema init, and verification."""

    _instance: Optional[PersistentNeo4jClient] = None
    _driver: Optional[AsyncDriver] = None
    _schema_initialized: bool = False

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        pool_size: int = 50,
        auto_init: bool = True,
    ):
        super().__init__(uri, user, password, pool_size)
        self._auto_init = auto_init

    @classmethod
    def get_instance(cls, auto_init: bool = True) -> PersistentNeo4jClient:
        if cls._instance is None:
            # Centralizzazione delle variabili d'ambiente
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "password")
            pool_size = int(os.getenv("NEO4J_POOL_SIZE", "50"))
            cls._instance = cls(uri, user, password, pool_size, auto_init)
        return cls._instance

    async def get_driver(self) -> AsyncDriver:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_pool_size=self.pool_size,
            )
        return self._driver

    async def close_driver(self, driver: AsyncDriver) -> None:
        pass  # Tiene aperta la connessione (Persistent)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def ensure_initialized(self) -> bool:
        """Robust initialization with retry logic (Tenacity pattern)."""
        if PersistentNeo4jClient._schema_initialized:
            return True
        try:
            driver = await self.get_driver()
            if self._auto_init and not await self._initialize_schema(driver):
                return False
            if not await self._verify_schema(driver):
                return False
            PersistentNeo4jClient._schema_initialized = True
            logger.info("[Client] Neo4j ready with verified schema")
            return True
        except Exception as e:
            logger.error(f"[Client] Initialization attempt failed: {e}")
            raise  # Rilancia per attivare il retry di tenacity

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
        PersistentNeo4jClient._instance = None
        PersistentNeo4jClient._schema_initialized = False

    # ── Schema helpers (private) ──

    async def _load_cypher(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Cypher file not found: {path}")
        with open(path, "r") as f:
            return f.read()

    async def _execute_script(
        self,
        driver: AsyncDriver,
        script: str,
        script_name: str,
        allow_failures: bool = False,
    ) -> bool:
        try:
            logger.info(f"[Schema] Executing {script_name}...")
            statements: list[str] = []
            current = ""
            for line in script.split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith("//"):
                    continue
                current += line + "\n"
                if stripped.endswith(";"):
                    statements.append(current)
                    current = ""

            async with driver.session() as session:
                for stmt in statements:
                    if not stmt.strip():
                        continue
                    try:
                        await session.run(stmt)
                    except exceptions.ClientError as e:
                        if allow_failures and "apoc.trigger" in stmt.lower():
                            logger.warning(f"[Schema] APOC trigger skipped: {e.message}")
                        else:
                            raise
                    except Exception:
                        if not allow_failures:
                            raise

            logger.info(f"[Schema] {script_name} OK")
            return True
        except Exception as e:
            logger.error(f"[Schema] {script_name} failed: {e}")
            return False

    async def _initialize_schema(
        self, driver: AsyncDriver, scripts_dir: Path | None = None
    ) -> bool:
        if scripts_dir is None:
            scripts_dir = Path(__file__).parent
        scripts = [
            ("01-schema.cypher", "Schema Definition", False),
            ("02-triggers.cypher", "APOC Triggers", True),
        ]
        for filename, desc, allow_fail in scripts:
            path = scripts_dir / filename
            if not path.exists():
                logger.warning(f"[Schema] Skipping {filename}: not found")
                continue
            content = await self._load_cypher(path)
            if not await self._execute_script(driver, content, desc, allow_fail):
                return False
            await asyncio.sleep(0.5)
        return True

    async def _verify_schema(self, driver: AsyncDriver) -> bool:
        logger.info("[Schema] Verifying...")
        try:
            async with driver.session() as session:
                c_res = await session.run("CALL db.constraints()")
                constraints = [r async for r in c_res]
                logger.info(f"[Schema] {len(constraints)} constraints")

                i_res = await session.run("CALL db.indexes()")
                indexes = [r async for r in i_res]
                logger.info(f"[Schema] {len(indexes)} indexes")

                for label in ["Recipe", "Model", "Experiment", "Checkpoint", "Component"]:
                    cnt_res = await session.run(f"MATCH (n:{label}) RETURN COUNT(n) AS count")
                    cnt = [r async for r in cnt_res]
                    if cnt:
                        logger.info(f"[Schema] {label}: {cnt[0]['count']} nodes")

                o_res = await session.run("""
                    MATCH (c:Checkpoint)
                    WHERE NOT (()-[:PRODUCED]->(c)) AND c.is_merging <> true
                    RETURN COUNT(c) AS orphan_count
                """)
                orphans = [r async for r in o_res]
                if orphans and orphans[0]["orphan_count"] > 0:
                    logger.warning(f"[Schema] {orphans[0]['orphan_count']} orphan checkpoints")

            logger.info("[Schema] Verification OK")
            return True
        except Exception as e:
            logger.error(f"[Schema] Verification failed: {e}")
            return False


# ───────────────────────────────────────────────
# 2. Streamlit UI — Ephemeral / Thread-safe Version
# ───────────────────────────────────────────────

class StreamlitNeo4jClient(Neo4jClient):
    """Fresh driver per query, optimized for Streamlit's rerun paradigm."""

    """
    Nel tuo codice streamlit:
        import streamlit as st
        from my_module import StreamlitNeo4jClient

        @st.cache_resource
        def get_streamlit_neo4j_client():
            # Streamlit gestirà questo client memorizzandolo nella cache dell'applicazione
            return StreamlitNeo4jClient(
                uri=st.secrets.get("NEO4J_URI", "bolt://localhost:7687"),
                user=st.secrets.get("NEO4J_USER", "neo4j"),
                password=st.secrets.get("NEO4J_PASSWORD", "password"),
            )
    """

    async def get_driver(self) -> AsyncDriver:
        return AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password),
            max_connection_pool_size=self.pool_size,
        )

    async def close_driver(self, driver: AsyncDriver) -> None:
        await driver.close()