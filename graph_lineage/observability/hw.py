"""GPU hardware metrics via pynvml (optional)."""

from __future__ import annotations

from typing import Any


def get_gpu_stats() -> dict[str, Any]:
    """Read GPU util/mem/temp via pynvml. Returns empty dict if unavailable."""
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        return {
            "gpu_util": util.gpu,
            "gpu_mem_used_mb": mem.used // (1024 * 1024),
            "gpu_mem_total_mb": mem.total // (1024 * 1024),
            "gpu_temp_c": temp,
        }
    except Exception:
        return {}
