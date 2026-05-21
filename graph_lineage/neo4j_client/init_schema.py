#!/usr/bin/env python3
"""
Neo4j Schema Initialization Script
Loads Cypher schema files in sequence at startup.

Executes:
  1. 01-schema.cypher — constraints, indexes, node/relationship definitions
  2. 02-triggers.cypher — APOC triggers for timestamps and validation

Idempotent: Safe to run multiple times (all Cypher uses IF NOT EXISTS)
"""

import sys
import time
import logging
from pathlib import Path

from neo4j import GraphDatabase, exceptions, WRITE_ACCESS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_cypher_file(path: Path) -> str:
    """Load Cypher script from file."""
    if not path.exists():
        raise FileNotFoundError(f"Cypher file not found: {path}")

    with open(path, 'r') as f:
        return f.read()


def execute_cypher_script(session, script: str, script_name: str, allow_apoc_failure: bool = False) -> bool:
    """
    Execute a Cypher script line by line.
    Handles multi-line statements and comments.

    Args:
        session: Neo4j session
        script: Cypher script content
        script_name: Name for logging
        allow_apoc_failure: If True, skip APOC procedure failures gracefully (for triggers)
    """
    try:
        logger.info(f"Executing {script_name}...")

        # Split by semicolon, removing comments and empty lines
        statements = []
        current_stmt = ""

        for line in script.split('\n'):
            # Skip comments and empty lines
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('//'):
                continue

            current_stmt += line + '\n'

            if line_stripped.endswith(';'):
                statements.append(current_stmt)
                current_stmt = ""

        # Execute each statement
        failed_statements = []
        for stmt in statements:
            if stmt.strip():
                try:
                    result = session.run(stmt)
                    result.consume()  # Ensure result is consumed
                except exceptions.ClientError as e:
                    # For trigger scripts, allow APOC procedure failures (cluster/permission issues)
                    if allow_apoc_failure and "apoc.trigger" in stmt.lower():
                        logger.warning(f"⚠ APOC trigger skipped (expected in non-write scenarios): {e.message}")
                        failed_statements.append(stmt[:100])
                    else:
                        logger.error(f"Error executing statement: {e}")
                        logger.error(f"Statement: {stmt[:200]}...")
                        raise
                except Exception as e:
                    logger.error(f"Error executing statement: {e}")
                    logger.error(f"Statement: {stmt[:200]}...")
                    raise

        logger.info(f"✓ {script_name} executed successfully")
        if failed_statements:
            logger.info(f"  (skipped {len(failed_statements)} APOC statements due to limitations)")
        return True

    except Exception as e:
        logger.error(f"✗ {script_name} failed: {e}")
        raise


def initialize_schema(neo4j_uri: str, username: str, password: str, scripts_dir: Path = None) -> bool:
    """
    Initialize Neo4j schema with Cypher scripts.

    Args:
        neo4j_uri: Connection URI (e.g., bolt://localhost:7687)
        username: Neo4j username
        password: Neo4j password
        scripts_dir: Directory containing 01-schema.cypher, 02-triggers.cypher

    Returns:
        True if successful, False otherwise
    """
    if scripts_dir is None:
        scripts_dir = Path(__file__).parent

    try:
        # Connect to Neo4j
        logger.info(f"Connecting to Neo4j at {neo4j_uri}...")
        driver = GraphDatabase.driver(neo4j_uri, auth=(username, password))

        # Verify connection using an explicit write session so the driver routes to leader
        with driver.session(default_access_mode=WRITE_ACCESS) as session:
            session.run("RETURN 1")
        logger.info("✓ Connected to Neo4j")

        # Load and execute schema scripts in order
        scripts = [
            ("01-schema.cypher", "Schema Definition (constraints, indexes)"),
            ("02-triggers.cypher", "APOC Triggers (timestamps, validation)"),
        ]

        for filename, description in scripts:
            script_path = scripts_dir / filename

            if not script_path.exists():
                logger.warning(f"Skipping {filename}: file not found at {script_path}")
                continue

            script_content = load_cypher_file(script_path)

            # Use a write session for schema changes and APOC trigger installation
            # Allow APOC failures gracefully for trigger scripts (may fail in certain cluster modes)
            allow_apoc_failure = filename == "02-triggers.cypher"
            with driver.session(default_access_mode=WRITE_ACCESS) as session:
                try:
                    execute_cypher_script(session, script_content, description, allow_apoc_failure=allow_apoc_failure)
                except Exception as e:
                    # For triggers, log warning and continue (schema are critical)
                    if allow_apoc_failure:
                        logger.warning(f"⚠ {description} had errors but proceeding (triggers are optional for setup)")
                    else:
                        raise

            # Brief pause between scripts
            time.sleep(1)

        logger.info("✓ Schema initialization complete!")
        driver.close()
        return True

    except exceptions.ServiceUnavailable:
        logger.error("Neo4j is not available. Retrying...")
        return False
    except Exception as e:
        logger.error(f"Schema initialization failed: {e}")
        return False


def main():
    """Entry point: initialize schema or run in resilient mode."""
    import os

    neo4j_uri = os.getenv('NEO4J_URI', 'neo4j://localhost:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PASSWORD', 'password')

    # Retry loop: Neo4j may not be ready yet
    max_retries = 30
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        logger.info(f"Schema init attempt {attempt + 1}/{max_retries}...")

        if initialize_schema(neo4j_uri, neo4j_user, neo4j_password):
            logger.info("Schema initialization successful!")
            sys.exit(0)

        if attempt < max_retries - 1:
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

    logger.error("Schema initialization failed after all retries")
    sys.exit(1)


if __name__ == "__main__":
    main()
