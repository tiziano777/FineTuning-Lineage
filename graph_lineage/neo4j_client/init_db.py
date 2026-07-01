#!/usr/bin/env python3
"""
Init script per Neo4j 5.x Community Edition.

Esegue in modo idempotente:
  - 01-schema.cypher    (CREATE CONSTRAINT / INDEX ... IF NOT EXISTS)  -> db 'neo4j'
  - 02-triggers.cypher  (CALL apoc.trigger.install(...))               -> db 'system'

Perche' serve questo script:
Neo4j non ha un meccanismo di auto-esecuzione tipo docker-entrypoint-initdb.d.
I file mountati in /import (o in qualunque altra cartella) NON vengono MAI
eseguiti automaticamente all'avvio del container: vanno lanciati esplicitamente
tramite il driver bolt (o cypher-shell).

Inoltre, a partire da APOC 5.x, le procedure apoc.trigger.install / .drop /
.stop / .start sono procedure di sistema e vanno invocate nel contesto del
database 'system' (non nel db applicativo 'neo4j').
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from neo4j import GraphDatabase, basic_auth
from neo4j.exceptions import ServiceUnavailable, AuthError

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "envelope_dev")

SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))
SCHEMA_FILE = SCRIPTS_DIR / "01-schema.cypher"
TRIGGERS_FILE = SCRIPTS_DIR / "02-triggers.cypher"

MAX_WAIT_SECONDS = 120
RETRY_INTERVAL_SECONDS = 2


def strip_comments(text: str) -> str:
    """Rimuove le righe di commento (// ...) preservando gli a-capo."""
    kept_lines = []
    for line in text.splitlines():
        if line.strip().startswith("//"):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def split_statements(text: str) -> list[str]:
    """Divide il file .cypher in singoli statement separati da ';'."""
    cleaned = strip_comments(text)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def wait_for_neo4j(driver) -> None:
    waited = 0
    while waited < MAX_WAIT_SECONDS:
        try:
            driver.verify_connectivity()
            print("[init_db] Connessione a Neo4j stabilita.")
            return
        except (ServiceUnavailable, AuthError) as exc:
            print(f"[init_db] Neo4j non ancora pronto ({exc.__class__.__name__}); "
                  f"retry tra {RETRY_INTERVAL_SECONDS}s...")
            time.sleep(RETRY_INTERVAL_SECONDS)
            waited += RETRY_INTERVAL_SECONDS
    raise RuntimeError("Neo4j non raggiungibile dopo l'attesa massima.")


def run_statements(driver, statements: list[str], database: str, label: str) -> None:
    with driver.session(database=database) as session:
        for i, stmt in enumerate(statements, start=1):
            preview = " ".join(stmt.split())[:90]
            try:
                session.run(stmt).consume()
                print(f"[init_db][{label}] ({i}/{len(statements)}) OK -> {preview}")
            except Exception as exc:
                print(f"[init_db][{label}] ({i}/{len(statements)}) ERRORE -> {preview}")
                print(f"    statement completo:\n{stmt}\n")
                print(f"    eccezione: {exc}")
                raise


def main() -> int:
    if not SCHEMA_FILE.exists():
        print(f"[init_db] File non trovato: {SCHEMA_FILE}", file=sys.stderr)
        return 1
    if not TRIGGERS_FILE.exists():
        print(f"[init_db] File non trovato: {TRIGGERS_FILE}", file=sys.stderr)
        return 1

    driver = GraphDatabase.driver(NEO4J_URI, auth=basic_auth(NEO4J_USER, NEO4J_PASSWORD))
    try:
        wait_for_neo4j(driver)

        schema_statements = split_statements(SCHEMA_FILE.read_text(encoding="utf-8"))
        trigger_statements = split_statements(TRIGGERS_FILE.read_text(encoding="utf-8"))

        print(f"[init_db] Eseguo {len(schema_statements)} statement di schema sul db 'neo4j'...")
        run_statements(driver, schema_statements, database="neo4j", label="schema")

        print(f"[init_db] Eseguo {len(trigger_statements)} statement di trigger sul db 'system'...")
        run_statements(driver, trigger_statements, database="system", label="trigger")

        print("[init_db] Completato con successo.")
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())