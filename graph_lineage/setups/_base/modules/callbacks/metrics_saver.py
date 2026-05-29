"""Callback to persist trainer log_history to disk at every eval/save event."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from transformers import TrainerCallback, TrainerState

logger = logging.getLogger(__name__)


class MetricsSaverCallback(TrainerCallback):
    """Write trainer.state.log_history to JSON on every evaluate and save event.

    This ensures intermediate metrics survive a crash and can be used
    to generate partial diagnostic plots via PlotManager.

    Every 500 global steps, also generates diagnostic plots via PlotManager
    into a subdirectory named ``plots-iter-<step>/``.
    """

    def __init__(
        self,
        metrics_path: Path,
        config_path: str = "config.yml",
        beta: float = 0.1,
        max_grad_norm: Optional[float] = 1.0,
        plot_every: int = 500,
    ):
        self.metrics_path = Path(metrics_path)
        self.config_path = config_path
        self.beta = beta
        self.max_grad_norm = max_grad_norm
        self.plot_every = plot_every
        self._last_plot_step = 0

    def on_evaluate(self, args, state: TrainerState, control, **kwargs):
        self._save(state)

    def on_save(self, args, state: TrainerState, control, **kwargs):
        self._save(state)

    def on_log(self, args, state: TrainerState, control, **kwargs):
        self._save(state)
        self._maybe_plot(state)

    def _save(self, state: TrainerState):
        self.metrics_path.mkdir(parents=True, exist_ok=True)
        out = self.metrics_path / "log_history.json"
        with open(out, "w") as f:
            json.dump(state.log_history, f)
        logger.info("Saved log_history (%d entries) to %s", len(state.log_history), out)

    def _maybe_plot(self, state: TrainerState):
        step = state.global_step
        if step < self.plot_every:
            return
        if step - self._last_plot_step < self.plot_every:
            return

        self._last_plot_step = step
        plot_dir = self.metrics_path / f"plots-iter-{step}"

        try:
            from modules.plots.plot_manager import PlotManager

            pm = PlotManager(
                config_path=self.config_path,
                beta=self.beta,
                max_grad_norm=self.max_grad_norm,
                output_base=plot_dir,
            )
            pm.run(state.log_history)
            logger.info("Plots saved at iteration %d to %s", step, plot_dir)
        except Exception:
            logger.exception("Plot generation failed at iteration %d (non-fatal)", step)
