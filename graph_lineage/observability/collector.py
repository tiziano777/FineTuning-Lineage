"""MetricsCollector: buffered dual-write to OpenLIT + local JSONL."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Buffers training metrics and flushes every K steps to OpenLIT + JSONL."""

    def __init__(self, experiment_id: str, metrics_uri: str | None, collect_every: int = 100) -> None:
        self._exp_id = experiment_id
        self._metrics_uri = metrics_uri
        self._k = collect_every
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def log_step(self, step: int, metrics: dict[str, Any]) -> None:
        """Buffer metrics. Flush every K steps."""
        entry = {
            "step": step,
            "experiment_id": self._exp_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            **metrics,
        }
        with self._lock:
            self._buffer.append(entry)
            if step > 0 and step % self._k == 0:
                self._flush()

    def _flush(self) -> None:
        """Dual-write: OpenLIT + local JSONL."""
        batch = list(self._buffer)
        self._buffer.clear()
        self._write_jsonl(batch)
        self._write_openlit(batch)

    def _write_openlit(self, entries: list[dict[str, Any]]) -> None:
        """Send batch to OpenLIT via SDK. Best-effort, no exception on failure."""
        try:
            import openlit  # noqa: F811

            for entry in entries:
                openlit.metric(
                    name=f"training.step.{entry['step']}",
                    value=entry,
                    attributes={"experiment_id": self._exp_id},
                )
        except ImportError:
            pass  # openlit not installed, skip
        except Exception:
            logger.debug("OpenLIT write failed, degrading gracefully")

    def _write_jsonl(self, entries: list[dict[str, Any]]) -> None:
        """Append entries to metrics_uri JSONL file."""
        if not self._metrics_uri:
            return
        path = Path(self._metrics_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def finalize(self) -> None:
        """Flush remaining buffer. Called by POST-execution."""
        with self._lock:
            if self._buffer:
                self._flush()


# Thread-local storage for current collector
_current_collector: threading.local = threading.local()


def set_collector(collector: MetricsCollector) -> None:
    """Set the current thread's MetricsCollector."""
    _current_collector.instance = collector


def get_collector() -> MetricsCollector | None:
    """Retrieve the current thread's MetricsCollector, or None."""
    return getattr(_current_collector, "instance", None)
