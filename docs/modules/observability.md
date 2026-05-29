# observability/ Module — Metrics Collection

## Overview

Collects training metrics (loss, accuracy, GPU stats) and writes to multiple backends (JSONL, OpenLIT).

**Location:** `graph_lineage/observability/`

## Public API

```python
from graph_lineage.observability import (
    MetricsCollector,
    get_gpu_stats,
)
```

## Components

### MetricsCollector
```python
class MetricsCollector:
    def __init__(self, metrics_dir: str):
        """Initialize JSONL + OpenLIT dual-write."""
    
    def log(self, step: int, metrics: dict) -> None
        """Log metrics: {loss: 0.23, accuracy: 0.95, gpu_util: 85}"""
        # Writes to JSONL file
        # Sends to OpenLIT (if configured)
    
    def flush(self) -> str
        """Finalize + return metrics_uri path."""
```

### get_gpu_stats
```python
def get_gpu_stats() -> dict:
    """Return GPU stats via pynvml."""
    return {
        "gpu_memory_used": 12345,
        "gpu_memory_total": 81920,
        "gpu_utilization": 85,
        "temperature": 62
    }
```

---

## Integration

**In training loop:**
```python
collector = MetricsCollector(metrics_dir="/nfs/metrics")

for epoch in range(10):
    loss = train_step()
    gpu_stats = get_gpu_stats()
    
    collector.log(step=epoch, metrics={
        "loss": loss,
        "gpu_util": gpu_stats["gpu_utilization"]
    })

metrics_uri = collector.flush()
```

**In POST execution:**
```python
# Server receives metrics_uri, stores in Checkpoint node
await create_checkpoint(ckp_id=..., metrics_uri=metrics_uri)
```

---

## Testing

Location: `tests/test_observability.py`

---

## See Also

- [lineage.md](lineage.md) — How metrics URIs are captured
- [docs/LINEAGE_SYSTEM_ARCHITECTURE.md](../LINEAGE_SYSTEM_ARCHITECTURE.md) — Metrics design

