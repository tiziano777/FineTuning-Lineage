"""Tests for MetricsCollector: buffering, JSONL write, finalize, graceful degradation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from graph_lineage.observability.collector import MetricsCollector, get_collector, set_collector


class TestMetricsCollectorBuffering:
    """Test that log_step buffers and flushes at K-step intervals."""

    def test_buffer_accumulates_before_k(self) -> None:
        collector = MetricsCollector("exp-1", None, collect_every=5)
        for step in range(1, 5):  # steps 1-4, none divisible by 5
            collector.log_step(step, {"loss": 0.5})
        assert len(collector._buffer) == 4

    def test_flush_at_k_step(self, tmp_path: Path) -> None:
        out = tmp_path / "metrics.jsonl"
        collector = MetricsCollector("exp-1", str(out), collect_every=5)
        for step in range(1, 6):  # step 5 triggers flush
            collector.log_step(step, {"loss": 0.5})
        assert len(collector._buffer) == 0
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 5

    def test_step_zero_does_not_flush(self) -> None:
        """Step 0 should not trigger flush (guard: step > 0)."""
        collector = MetricsCollector("exp-1", None, collect_every=5)
        collector.log_step(0, {"loss": 1.0})
        assert len(collector._buffer) == 1

    def test_multiple_flushes(self, tmp_path: Path) -> None:
        out = tmp_path / "metrics.jsonl"
        collector = MetricsCollector("exp-1", str(out), collect_every=3)
        for step in range(1, 10):
            collector.log_step(step, {"loss": float(step)})
        # Flushes at step 3, 6, 9 => 9 entries written, buffer empty
        assert len(collector._buffer) == 0
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 9


class TestMetricsCollectorJSONL:
    """Test JSONL output format."""

    def test_jsonl_format(self, tmp_path: Path) -> None:
        out = tmp_path / "metrics.jsonl"
        collector = MetricsCollector("exp-42", str(out), collect_every=2)
        collector.log_step(1, {"loss": 0.3, "lr": 1e-4})
        collector.log_step(2, {"loss": 0.2, "lr": 1e-4})
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["step"] == 1
        assert entry["experiment_id"] == "exp-42"
        assert entry["loss"] == 0.3
        assert "ts" in entry

    def test_no_metrics_uri_skips_jsonl(self) -> None:
        collector = MetricsCollector("exp-1", None, collect_every=1)
        collector.log_step(1, {"loss": 0.5})
        # No error, just no file written
        assert len(collector._buffer) == 0

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "metrics.jsonl"
        collector = MetricsCollector("exp-1", str(out), collect_every=1)
        collector.log_step(1, {"loss": 0.5})
        assert out.exists()


class TestMetricsCollectorFinalize:
    """Test finalize flushes remaining buffer."""

    def test_finalize_flushes_remaining(self, tmp_path: Path) -> None:
        out = tmp_path / "metrics.jsonl"
        collector = MetricsCollector("exp-1", str(out), collect_every=100)
        for step in range(1, 4):
            collector.log_step(step, {"loss": 0.5})
        assert len(collector._buffer) == 3
        collector.finalize()
        assert len(collector._buffer) == 0
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_finalize_noop_when_empty(self) -> None:
        collector = MetricsCollector("exp-1", None, collect_every=100)
        collector.finalize()  # Should not raise
        assert len(collector._buffer) == 0


class TestOpenLITGracefulDegradation:
    """Test that missing openlit does not break collection."""

    def test_import_error_handled(self, tmp_path: Path) -> None:
        out = tmp_path / "metrics.jsonl"
        collector = MetricsCollector("exp-1", str(out), collect_every=1)
        with patch.dict("sys.modules", {"openlit": None}):
            collector.log_step(1, {"loss": 0.5})
        # JSONL still written despite openlit failure
        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1


class TestThreadLocalCollector:
    """Test get_collector / set_collector thread-local storage."""

    def test_set_and_get(self) -> None:
        collector = MetricsCollector("exp-1", None)
        set_collector(collector)
        assert get_collector() is collector

    def test_get_returns_none_by_default(self) -> None:
        # In a fresh thread-local state, should return None
        import threading

        result = [None]

        def target() -> None:
            result[0] = get_collector()

        t = threading.Thread(target=target)
        t.start()
        t.join()
        assert result[0] is None
