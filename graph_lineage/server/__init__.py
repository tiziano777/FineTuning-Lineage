"""Lineage Server — FastAPI application for lineage tracking.

This server receives PRE/POST lifecycle requests from remote GPU workers
running the Client SDK, processes them (rule engine, Neo4j writes), and
returns results.

Run with: uvicorn graph_lineage.server.app:app --host 0.0.0.0 --port 8000
"""
