"""Hard Negative Filter — NLP-based selection of optimal rejected candidates.

3-phase pipeline:
  1. Intercept degenerate candidates (loops/truncation) → priority reject
  2. Filter false negatives (ROUGE-L too close to gold)
  3. Multi-attribute scoring → select best hard negative

Fallback strategies when no candidate survives:
  - "drop": return None (sample skipped)
  - "temperature": delegate to temperature-based selection
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from rouge_score import rouge_scorer
from scipy.stats import entropy as scipy_entropy

logger = logging.getLogger(__name__)


@dataclass
class HardNegativeConfig:
    """Configuration for hard negative selection."""

    enabled: bool = True
    fallback: Literal["drop", "temperature"] = "temperature"
    rouge_delta: float = 0.08
    tau: float = 0.5
    entropy_min: float = 0.3
    ttr_min: float = 0.2
    w1: float = 0.2  # entropy
    w2: float = 0.2  # TTR
    w3: float = 0.4  # ROUGE distance from tau
    w4: float = 0.2  # length penalty


class HardNegativeFilter:
    """Selects the optimal hard negative from K inference candidates."""

    def __init__(self, config: HardNegativeConfig):
        self.config = config
        self._scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)

    def select(
        self,
        candidates: list[dict],
        gold_content: str,
        temperature: float | None = None,
    ) -> dict | None:
        """Select the best hard negative from candidates.

        Args:
            candidates: List of inference_item dicts (with 'content', 'inference_params').
            gold_content: The chosen/gold text to compare against.
            temperature: Temperature for fallback selection.

        Returns:
            Best candidate dict, or None if fallback=drop and no valid candidate.
        """
        if not candidates:
            logger.debug("HN filter: no candidates provided")
            return None

        logger.debug("HN filter: evaluating %d candidates (gold_len=%d tokens)",
                     len(candidates), len(gold_content.split()))
        gold_tokens = gold_content.split()

        # Phase 1: Intercept degenerate candidates (loops/truncation)
        degenerate = self._find_degenerate(candidates)
        if degenerate:
            content_preview = self._get_content(degenerate)[:80]
            logger.info("HN Phase1 -> degenerate intercepted as rejected: '%s...'", content_preview)
            return degenerate

        # Phase 2: Filter false negatives (too close to gold)
        threshold = 1.0 - self.config.rouge_delta
        surviving = []
        filtered_count = 0
        for cand in candidates:
            content = self._get_content(cand)
            rouge_l = self._compute_rouge_l(content, gold_content)
            if rouge_l <= threshold:
                surviving.append(cand)
                logger.debug("HN Phase2 -> kept candidate (ROUGE-L=%.3f <= %.3f)", rouge_l, threshold)
            else:
                filtered_count += 1
                logger.debug("HN Phase2 -> filtered false negative (ROUGE-L=%.3f > %.3f)", rouge_l, threshold)

        if filtered_count:
            logger.info("HN Phase2 -> filtered %d/%d candidates as false negatives (ROUGE > %.2f)",
                        filtered_count, len(candidates), threshold)

        # Phase 3: Multi-attribute scoring
        if surviving:
            best = self._rank_candidates(surviving, gold_tokens, gold_content)
            if best is not None:
                logger.info("HN Phase3 -> selected best candidate (score ranking from %d survivors)", len(surviving))
                return best

        # Fallback
        if self.config.fallback == "temperature" and temperature is not None:
            logger.warning("HN fallback -> no valid candidates, using temperature selection (t=%.2f)", temperature)
            return self._select_by_temperature(candidates, temperature)

        # fallback=drop OR temperature is None
        logger.warning("HN fallback -> DROP sample (no valid candidates, fallback=%s)", self.config.fallback)
        return None

    def _find_degenerate(self, candidates: list[dict]) -> dict | None:
        """Find degenerate candidate (loop/truncation) with lowest entropy."""
        worst: dict | None = None
        worst_entropy = float("inf")

        for cand in candidates:
            content = self._get_content(cand)
            tokens = content.split()
            if len(tokens) < 3:
                logger.debug("HN Phase1 -> candidate too short (%d tokens), marked degenerate", len(tokens))
                if worst is None or 0.0 < worst_entropy:
                    worst = cand
                    worst_entropy = 0.0
                continue

            ent = self._compute_entropy(tokens)
            ttr = self._compute_ttr(tokens)

            if ent < self.config.entropy_min or ttr < self.config.ttr_min:
                logger.debug("HN Phase1 -> degenerate detected (entropy=%.3f, ttr=%.3f) | thresholds: ent<%.2f or ttr<%.2f",
                             ent, ttr, self.config.entropy_min, self.config.ttr_min)
                if ent < worst_entropy:
                    worst = cand
                    worst_entropy = ent
            else:
                logger.debug("HN Phase1 -> candidate OK (entropy=%.3f, ttr=%.3f)", ent, ttr)

        return worst

    def _rank_candidates(
        self, candidates: list[dict], gold_tokens: list[str], gold_content: str
    ) -> dict | None:
        """Score candidates with multi-attribute formula, return best."""
        best_score = float("-inf")
        best_cand: dict | None = None
        gold_len = len(gold_tokens)

        for idx, cand in enumerate(candidates):
            content = self._get_content(cand)
            tokens = content.split()
            if not tokens:
                continue

            ent = self._compute_entropy(tokens)
            ttr = self._compute_ttr(tokens)
            rouge_l = self._compute_rouge_l(content, gold_content)
            length_pen = self._compute_length_penalty(len(tokens), gold_len)

            score = (
                self.config.w1 * ent
                + self.config.w2 * ttr
                - self.config.w3 * abs(rouge_l - self.config.tau)
                - self.config.w4 * length_pen
            )

            logger.debug(
                "HN Phase3 -> cand[%d] score=%.4f (ent=%.3f, ttr=%.3f, rouge_l=%.3f, len_pen=%.3f)",
                idx, score, ent, ttr, rouge_l, length_pen
            )

            if score > best_score:
                best_score = score
                best_cand = cand

        if best_cand is not None:
            logger.debug("HN Phase3 -> winner score=%.4f", best_score)
        return best_cand

    def _compute_entropy(self, tokens: list[str]) -> float:
        """Normalized unigram entropy in [0, 1]."""
        if len(tokens) <= 1:
            return 0.0
        counts = Counter(tokens)
        probs = [c / len(tokens) for c in counts.values()]
        max_entropy = math.log2(len(tokens))
        if max_entropy == 0:
            return 0.0
        raw = scipy_entropy(probs, base=2)
        return min(raw / max_entropy, 1.0)

    def _compute_ttr(self, tokens: list[str]) -> float:
        """Type-Token Ratio: unique tokens / total tokens."""
        if not tokens:
            return 0.0
        return len(set(tokens)) / len(tokens)

    def _compute_rouge_l(self, candidate: str, gold: str) -> float:
        """ROUGE-L F1 score between candidate and gold."""
        if not candidate or not gold:
            return 0.0
        scores = self._scorer.score(gold, candidate)
        return scores["rougeL"].fmeasure

    def _compute_length_penalty(self, cand_len: int, gold_len: int) -> float:
        """Normalized length difference penalty."""
        if gold_len == 0:
            return 1.0
        return abs(cand_len - gold_len) / gold_len

    @staticmethod
    def _get_content(item: dict) -> str:
        """Extract text content from an inference item."""
        return item.get("content") or ""

    @staticmethod
    def _select_by_temperature(items: list[dict], temperature: float) -> dict:
        """Fallback: pick item matching temperature."""
        for item in items:
            params = item.get("inference_params") or {}
            if params.get("temperature") == temperature:
                return item
        return items[0] if items else {}
