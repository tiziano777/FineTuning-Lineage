"""Hard Negative Filter — NLP-based selection of optimal rejected candidates for DPO.

3-phase pipeline:
  1. Detect and quarantine degenerate candidates (loops/hallucinations/truncation).
     If ALL candidates are degenerate, the sample is appended to hallucinations.jsonl
     and None is returned regardless of fallback strategy.
  2. Filter false negatives (ROUGE-L too close to gold, i.e., near-duplicates).
  3. Multi-attribute scoring → select best hard negative.

Fallback strategies when no candidate survives phases 1-2:
  - "drop": return None (sample skipped)
  - "temperature": delegate to temperature-based selection

Recommended usage — two-pass workflow
--------------------------------------
  1. Call compute_stats(uri) once on the full dataset to derive calibrated
     thresholds from the real corpus distributions (entropy, TTR, ROUGE-L).
     This returns a HardNegativeConfig pre-populated with data-driven values.

  2. Instantiate HardNegativeFilter(config) and call select() once per sample.

This separates global calibration (corpus-level statistics) from local selection
(per-sample K-candidate pool), giving both statistically stable thresholds and
fast per-sample inference.

Design principles:
  - No arbitrary tau: ROUGE-L distance from gold is maximised, not targeted.
  - Corpus-calibrated thresholds: entropy_min, ttr_min, and adaptive_k are all
    derived from the actual data distribution, not magic numbers.
  - Per-sample adaptive mode still applies on top: percentile within the local
    pool acts as a secondary signal when K is large enough.
  - TTR is log-normalised to be length-agnostic (Zipf-robust).
  - All scoring features are min-max normalised before weighted combination.
  - Degenerate candidates are ALWAYS quarantined, never returned as hard negatives.

Dataset schema (Arrow / JSONL)
-------------------------------
Each sample is expected to have:
  - "chosen":   list of {role, content} messages — last assistant turn = gold.
  - "rejected": list of candidate responses. Each candidate is itself a list of
                {role, content} messages (multi-turn format). compute_stats and
                select() both accept this nested format and extract the last
                assistant message as the candidate text.
"""
from __future__ import annotations

import json
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rouge_score import rouge_scorer
from scipy.stats import entropy as scipy_entropy

logger = logging.getLogger(__name__)

HALLUCINATIONS_FILE = Path("hallucinations.jsonl")

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _interpolated_percentile(sorted_values: list[float], p: float) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_values[0]
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac

def _extract_last_assistant_text(messages: list[dict] | dict) -> str:
    """Estrae l'ultimo turno dell'assistant. Gestisce sia liste di messaggi 
    che strutture dizionario contenenti i messaggi."""
    # Se il candidato è avvolto in un dizionario con metadati (es. per temperatura)
    if isinstance(messages, dict):
        # Direct content field (raw candidate format: {"content": "...", "inference_params": {...}})
        if "content" in messages and "messages" not in messages:
            return messages.get("content") or ""
        messages = messages.get("messages", [])
        
    if not messages or not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            return msg.get("content") or ""
    return messages[-1].get("content") if isinstance(messages[-1], dict) else ""

def _extract_candidates_from_sample(sample: dict) -> tuple[list, str]:
    """Extract candidates and gold text from a sample.
    
    Supports two formats:
    1. Post-processed: {"chosen": [...], "rejected": [...]}
    2. Raw messages: {"messages": [{"role": "ASSISTANT", "positives": [...], "negatives": [...]}]}
    """
    # Format 1: already has chosen/rejected
    chosen = sample.get("chosen") or []
    rejected = sample.get("rejected") or []
    if chosen and rejected:
        gold_text = _extract_last_assistant_text(chosen)
        return rejected, gold_text

    # Format 2: raw messages with positives/negatives
    messages = sample.get("messages") or []
    gold_text = ""
    candidates = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role") or "").upper()
        if role == "ASSISTANT":
            positives = msg.get("positives") or []
            negatives = msg.get("negatives") or []
            if positives:
                # Gold = first positive's content
                first_pos = positives[0]
                gold_text = first_pos.get("content", "") if isinstance(first_pos, dict) else ""
            candidates = negatives
            break  # take first assistant generation turn

    return candidates, gold_text

def _compute_entropy(tokens: list[str]) -> float:
    if len(tokens) <= 1:
        return 0.0
    counts = Counter(tokens)
    if len(counts) <= 1:
        return 0.0
    probs = [c / len(tokens) for c in counts.values()]
    raw = scipy_entropy(probs, base=2)
    # CORREZIONE: Si normalizza sul log2 dei token UNICI, non totali
    return raw / math.log2(len(counts))

def _compute_log_ttr(tokens: list[str]) -> float:
    n = len(tokens)
    if n < 2:
        return 1.0
    n_unique = len(set(tokens))
    if n_unique == 1:
        return 0.0
    return math.log(n_unique) / math.log(n)

def _rouge_l(scorer, candidate_text: str, gold_text: str) -> float:
    if not candidate_text or not gold_text:
        return 0.0
    return scorer.score(gold_text, candidate_text)["rougeL"].fmeasure

def _sigmoid(x: float) -> float:
    try:
        return 1 / (1 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


# ---------------------------------------------------------------------------
# Classe HardNegativeConfig
# ---------------------------------------------------------------------------

class HardNegativeConfig:
    def __init__(
        self, 
        uri: str | Path, 
        degenerate_percentile: float = 0.15,
        fn_rouge_percentile: float = 0.30,
        fallback: Literal["drop", "temperature"] = "temperature",
        enabled: bool = True
    ):
        self._uri = Path(uri)
        if not self._uri.exists():
            raise FileNotFoundError(f"Dataset non trovato: {self._uri}")

        self._degenerate_percentile = degenerate_percentile
        self._fn_rouge_percentile = fn_rouge_percentile
        self._fallback = fallback
        self._enabled = enabled

        self._config_dict: dict = {}
        self._pipeline()

    def get_config(self, entry_uri: str | None = None) -> dict:
        return self._config_dict

    def _pipeline(self):
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)
        logger.info("HardNegativeConfig: scansione globale del dataset '%s'", self._uri)

        entropy_values = []
        ttr_values = []
        rouge_values = []
        length_penalty_values = []
        
        degenerate_count = 0
        n_samples = 0
        n_candidates = 0
        k_distribution = Counter()
        global_vocab = set()

        # CORREZIONE: Unificato il loop. Calcoliamo le statistiche in un unico passo 
        # per evitare di rileggere l'intero dataset da disco due volte.
        for sample in self._iter_dataset():
            candidates, gold_text = _extract_candidates_from_sample(sample)
            if not candidates:
                continue

            n_samples += 1
            k_distribution[len(candidates)] += 1
            gold_len = len(gold_text.split())

            for cand in candidates:
                n_candidates += 1
                text = _extract_last_assistant_text(cand)
                tokens = text.split()
                global_vocab.update(tokens)

                if len(tokens) < 3:
                    entropy_values.append(0.0)
                    ttr_values.append(0.0)
                    degenerate_count += 1
                    r = _rouge_l(scorer, text, gold_text)
                    rouge_values.append(r)
                    length_penalty_values.append(1.0)
                    continue

                ent = _compute_entropy(tokens)
                ttr = _compute_log_ttr(tokens)
                r = _rouge_l(scorer, text, gold_text)
                
                len_pen = min(abs(len(tokens) - gold_len) / max(gold_len, 1), 1.0)

                entropy_values.append(ent)
                ttr_values.append(ttr)
                rouge_values.append(r)
                length_penalty_values.append(len_pen)

                if ent == 0.0 or ttr == 0.0:
                    degenerate_count += 1

        if n_candidates == 0:
            raise ValueError("Il dataset non ha prodotto candidati validi.")

        corpus_vocab_size = max(len(global_vocab), 2)
        entropy_values.sort()
        ttr_values.sort()
        rouge_values.sort()

        entropy_min = _interpolated_percentile(entropy_values, self._degenerate_percentile)
        ttr_min = _interpolated_percentile(ttr_values, self._degenerate_percentile)
        target_rouge = _interpolated_percentile(rouge_values, self._fn_rouge_percentile)

        def _get_stats(vals: list[float]) -> tuple[float, float]:
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            return mean, max(math.sqrt(var), 1e-9)

        mean_ent, std_ent = _get_stats(entropy_values)
        mean_ttr, std_ttr = _get_stats(ttr_values)
        mean_r, std_r = _get_stats(rouge_values)
        mean_lp, std_lp = _get_stats(length_penalty_values)

        if std_r > 1e-9:
            adaptive_k = (mean_r - target_rouge) / std_r
            adaptive_k = max(0.0, min(adaptive_k, 5.0))
        else:
            adaptive_k = 0.0

        self._config_dict = {
            "enabled": self._enabled,
            "fallback": self._fallback,
            "degenerate_percentile": self._degenerate_percentile,
            "fn_rouge_percentile": self._fn_rouge_percentile,
            "corpus_vocabulary_size": corpus_vocab_size,
            "entropy_min": entropy_min,
            "ttr_min": ttr_min,
            "adaptive_k": adaptive_k,
            "global_stats": {
                "entropy": {"mean": mean_ent, "std": std_ent},
                "ttr": {"mean": mean_ttr, "std": std_ttr},
                "rouge": {"mean": mean_r, "std": std_r},
                "length_pen": {"mean": mean_lp, "std": std_lp},
                "target_rouge_cutoff": target_rouge
            },
            "metrics_summary": {
                "total_samples": n_samples,
                "total_candidates": n_candidates,
                "degenerate_count": degenerate_count,
                "degenerate_ratio": degenerate_count / max(n_candidates, 1),
                "k_distribution": dict(sorted(k_distribution.items())),
            }
        }
        logger.info("HardNegativeConfig: Calibrazione globale completata con successo.")

    def _iter_dataset(self):
        # Handle directories: find data files inside and iterate them
        if self._uri.is_dir():
            yield from self._iter_directory()
            return
        suffix = self._uri.suffix.lower()
        if suffix == ".arrow":
            yield from self._iter_arrow(self._uri)
        elif suffix in {".jsonl", ".json", ".jsonlines"}:
            yield from self._iter_jsonl(self._uri)
        else:
            try:
                yield from self._iter_arrow(self._uri)
            except Exception:
                yield from self._iter_jsonl(self._uri)

    def _iter_directory(self):
        """Iterate data files in a directory (arrow > jsonl.gz > jsonl > parquet)."""
        arrow_files = sorted(self._uri.glob("*.arrow"))
        if arrow_files:
            for f in arrow_files:
                yield from self._iter_arrow(f)
            return
        jsonl_files = sorted(self._uri.glob("*.jsonl")) + sorted(self._uri.glob("*.jsonlines"))
        if jsonl_files:
            for f in jsonl_files:
                yield from self._iter_jsonl(f)
            return
        parquet_files = sorted(self._uri.glob("*.parquet"))
        if parquet_files:
            yield from self._iter_parquet(parquet_files)
            return
        raise FileNotFoundError(
            f"Nessun file dati (arrow/jsonl/parquet) trovato in: {self._uri}"
        )

    def _iter_arrow(self, filepath: Path | None = None):
        import pyarrow as pa
        import pyarrow.ipc as ipc
        
        target = filepath or self._uri
        # CORREZIONE: Robustezza nella lettura di file Arrow. 
        # Tenta prima lo Stream reader (standard di HF datasets) e poi fallback su File reader.
        try:
            with ipc.open_stream(target) as reader:
                table = reader.read_all()
                for row in table.to_pylist():
                    yield row
        except Exception:
            with ipc.open_file(target) as reader:
                table = reader.read_all()
                for row in table.to_pylist():
                    yield row

    def _iter_jsonl(self, filepath: Path | None = None):
        target = filepath or self._uri
        with open(target, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)

    def _iter_parquet(self, files: list[Path]):
        import pandas as pd
        for f in files:
            df = pd.read_parquet(f)
            for row in df.to_dict("records"):
                yield row


# ---------------------------------------------------------------------------
# HardNegativeFilter
# ---------------------------------------------------------------------------

class HardNegativeFilter:
    def __init__(self, config: dict):
        self.config = config
        self._scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)

        self._entropy_min = config.get("entropy_min", 0.0)
        self._ttr_min = config.get("ttr_min", 0.0)
        
        self._g_stats = config.get("global_stats", {})
        self._rouge_cutoff_global = self._g_stats.get("target_rouge_cutoff", 1.0)

        self._w_entropy = config.get("w_entropy", 0.20)
        self._w_ttr = config.get("w_ttr", 0.20)
        self._w_rouge_dist = config.get("w_rouge_dist", 0.40)
        self._w_length_pen = config.get("w_length_pen", 0.20)
        
        self._hallucinations_path = HALLUCINATIONS_FILE

    def select(
        self,
        candidates: list,
        gold_content: str,
        temperature: float | None = None,
        sample_metadata: dict | None = None,
        hn_filter_entry_stats: dict | None = None,
    ) -> dict | list | None:
        if not self.config.get("enabled", True):
            return candidates[0] if candidates else None
        if not candidates:
            return None

        clean, _ = self._partition_degenerate(candidates)
        if not clean:
            self._append_hallucinations(candidates, sample_metadata)
            return None

        surviving, _ = self._filter_false_negatives(clean, gold_content)

        if surviving:
            best = self._rank_candidates(surviving, gold_content)
            if best is not None:
                return best

        if self.config.get("fallback") == "temperature" and temperature is not None:
            return self._select_by_temperature(clean or candidates, temperature)

        return None

    def _partition_degenerate(self, candidates: list) -> tuple[list, list]:
        clean = []
        degenerate = []

        for cand in candidates:
            content = _extract_last_assistant_text(cand)
            tokens = content.split()
            
            if len(tokens) < 3:
                degenerate.append(cand)
                continue

            ent = _compute_entropy(tokens)
            ttr = _compute_log_ttr(tokens)

            if ent < self._entropy_min or ttr < self._ttr_min:
                degenerate.append(cand)
            else:
                clean.append(cand)

        return clean, degenerate

    def _filter_false_negatives(self, candidates: list, gold_content: str) -> tuple[list, int]:
        surviving = []
        filtered_count = 0

        for cand in candidates:
            content = _extract_last_assistant_text(cand)
            r_score = _rouge_l(self._scorer, content, gold_content)
            
            if r_score <= self._rouge_cutoff_global:
                surviving.append(cand)
            else:
                filtered_count += 1

        return surviving, filtered_count

    def _rank_candidates(self, candidates: list, gold_content: str):
        if not candidates:
            return None

        gold_len = len(gold_content.split())
        best_score = float("-inf")
        best_cand = None

        def _soft_norm(val: float, key: str, invert: bool = False) -> float:
            stats = self._g_stats.get(key, {"mean": 0.5, "std": 1.0})
            z = (val - stats["mean"]) / stats["std"]
            score = _sigmoid(z)
            return (1.0 - score) if invert else score

        for cand in candidates:
            content = _extract_last_assistant_text(cand)
            tokens = content.split()
            
            if not tokens:
                continue

            ent = _compute_entropy(tokens)
            ttr = _compute_log_ttr(tokens)
            rouge_l = _rouge_l(self._scorer, content, gold_content)
            len_pen = min(abs(len(tokens) - gold_len) / max(gold_len, 1), 1.0)

            n_ent = _soft_norm(ent, "entropy")
            n_ttr = _soft_norm(ttr, "ttr")
            n_dist = _soft_norm(rouge_l, "rouge", invert=True) 
            n_pen = _soft_norm(len_pen, "length_pen", invert=True)

            score = (
                self._w_entropy * n_ent
                + self._w_ttr * n_ttr
                + self._w_rouge_dist * n_dist
                + self._w_length_pen * n_pen
            )

            if score > best_score:
                best_score = score
                best_cand = cand

        return best_cand

    def _append_hallucinations(self, candidates: list, sample_metadata: dict | None) -> None:
        # Serializzazione sicura convertendo eventuali strutture non primitive
        record = {"candidates": candidates, "metadata": sample_metadata or {}}
        try:
            with open(self._hallucinations_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.error("HN Scrittura fallita su %s: %s", self._hallucinations_path, exc)

    @staticmethod
    def _select_by_temperature(items: list, temperature: float):
        if not items:
            return {}
        # CORREZIONE: Gestione sicura nel caso 'it' sia una lista (multi-turn) 
        # o un dizionario contenente metadati aggiuntivi.
        def _get_temp(it):
            if isinstance(it, dict):
                return (it.get("inference_params") or {}).get("temperature", float("inf"))
            return float("inf")

        return min(items, key=lambda it: abs(_get_temp(it) - temperature))