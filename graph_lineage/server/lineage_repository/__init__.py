"""Lineage tracking module — rule engine and Neo4j operations.

The client-server decorator (@lineage_tracker) lives in the Client SDK
at setups/_base/modules/lineage/. This module provides the server-side
logic: run-type detection and Neo4j writes (neo4j_ops).
"""
