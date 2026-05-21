"""Observability layer: metrics collection with dual-write (OpenLIT + local JSONL)."""

from __future__ import annotations

from graph_lineage.observability.collector import MetricsCollector, get_collector, set_collector

__all__ = ["MetricsCollector", "get_collector", "set_collector"]
