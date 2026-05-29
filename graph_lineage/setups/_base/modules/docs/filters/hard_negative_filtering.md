# Hard Negative Filtering — Technical Documentation

**Last updated:** 2026-05-29  
**Module:** `modules/filters/hard_negative_filtering.py`  
**Test file:** `tests/test_hard_negative_filtering.py`

---

## Overview

The Hard Negative Filtering module implements an NLP-based 3-phase pipeline for selecting optimal "rejected" candidates in DPO (Direct Preference Optimization) training. Instead of randomly picking a negative or using temperature-based selection, it uses corpus-calibrated metrics to find candidates that are:

1. **Not degenerate** (no loops, hallucinations, or truncated outputs)
2. **Not false negatives** (not near-duplicates of the gold/chosen response)
3. **Maximally informative** as training signal (best multi-attribute score)

---

## Architecture

### Two-Class Design

| Class | Responsibility |
|-------|---------------|
| `HardNegativeConfig` | Corpus-level calibration — scans the full dataset once to derive thresholds (entropy_min, ttr_min, ROUGE-L cutoff) |
| `HardNegativeFilter` | Per-sample selection — takes a pool of K candidates and returns the best hard negative |

### Pipeline Flow (in `prepare.py`)

```
config.yml → HardNegativeConfig(uri) → get_config() → inject weights → HardNegativeFilter(config) → template_fn(..., hn_filter=filter)
```

### 3-Phase Selection Pipeline

```
Candidates (K pool)
    │
    ▼
Phase 1: Degenerate Detection
    - Entropy < threshold → quarantine
    - TTR < threshold → quarantine
    - len(tokens) < 3 → quarantine
    - ALL degenerate? → log to hallucinations.jsonl, return None
    │
    ▼
Phase 2: False Negative Filtering
    - ROUGE-L(candidate, gold) > cutoff → filter out
    - Removes near-duplicates of the chosen response
    │
    ▼
Phase 3: Multi-Attribute Scoring
    - Normalize: entropy, TTR, ROUGE-L distance, length penalty
    - Weighted sum: w1*ent + w2*ttr + w3*rouge_dist + w4*len_pen
    - Select argmax
    │
    ▼
Fallback (if no candidate survives):
    - "temperature": delegate to temperature-based selection from clean pool
    - "drop": return None (sample skipped)
```

---

## NLP Metrics Used

### Normalized Entropy
```
H_norm = H(tokens) / log2(|unique_tokens|)
```
Range: [0, 1]. Detects repetitive/looping text (H_norm ≈ 0).

### Log-TTR (Type-Token Ratio)
```
log_TTR = log(|unique_tokens|) / log(|total_tokens|)
```
Length-agnostic diversity measure (Zipf-robust). Range: [0, 1].

### ROUGE-L F-measure
Longest common subsequence overlap with gold. Used to:
- Filter false negatives (too similar to gold)
- Score candidates (inverted: lower ROUGE = more different = better hard negative)

### Length Penalty
```
len_pen = min(|len(cand) - len(gold)| / max(len(gold), 1), 1.0)
```
Penalizes candidates with very different length from gold.

### Soft Normalization (Sigmoid z-score)
All features are normalized using corpus-level mean/std:
```
z = (value - mean) / std
score = sigmoid(z)
```
This maps features to (0, 1) using the global distribution as reference.

---

## Configuration (`config.yml`)

```yaml
hard_negative_enabled: true
hard_negative_params:
  config_based_fallback: temperature  # "temperature" | "drop"
  w1: 0.2   # entropy weight
  w2: 0.2   # TTR weight
  w3: 0.4   # ROUGE-L distance weight (dominant)
  w4: 0.2   # length penalty weight
```

---

## Modifiche Apportate (2026-05-29)

### Bug Fix 1: Pipeline Integration Broken (CRITICAL)
**Problema:** `prepare.py` never created a `HardNegativeFilter` instance. Only `HardNegativeConfig` was instantiated, and the template function never received the `hn_filter` argument. The hard negative selection was **dead code** — all samples fell through to temperature-based selection.

**Fix:** `prepare.py` now:
1. Creates `HardNegativeConfig(uri=uri)` for calibration
2. Gets the config dict via `get_config()`
3. Injects weights from `config.yml` `hard_negative_params`
4. Creates `HardNegativeFilter(config_dict)`
5. Passes both `hn_filter` and `hn_filter_entry_stats` to the template function

### Bug Fix 2: `get_config()` Signature Mismatch
**Problema:** Called as `get_config(entry_uri=entry.dist_uri)` but method accepted no parameters.  
**Fix:** Added optional `entry_uri` parameter (currently unused but kept for API compatibility).

### Bug Fix 3: `HardNegativeFilter.select()` Missing Parameter
**Problema:** Template called `hn_filter.select(..., hn_filter_entry_stats=...)` but the method didn't accept this kwarg → `TypeError` at runtime.  
**Fix:** Added `hn_filter_entry_stats: dict | None = None` to `select()` signature.

### Bug Fix 4: Directory Iteration Not Supported
**Problema:** `HardNegativeConfig(uri=...)` received directory paths (from recipe entries) but `_iter_dataset()` only handled single files.  
**Fix:** Added `_iter_directory()` method that discovers and iterates arrow/jsonl/parquet files within a directory.

### Bug Fix 5: `_extract_last_assistant_text` Didn't Handle Raw Candidates
**Problema:** Raw candidates have format `{"content": "...", "inference_params": {...}}` but the function only handled message-list format.  
**Fix:** Added detection of direct `content` key in dict format.

### Bug Fix 6: `_extract_candidates_from_sample` Only Handled Post-Processed Data
**Problema:** `HardNegativeConfig._pipeline()` iterates raw data with `messages/positives/negatives` format, but `_extract_candidates_from_sample` only handled `chosen/rejected` top-level format.  
**Fix:** Added fallback to parse raw messages format (extract first positive as gold, negatives as candidates).

### Bug Fix 7: `hn_filter_entry_stats` Uninitialized When Disabled
**Problema:** If `hn_enabled=False`, `hn_filter_entry_stats` was never assigned → `NameError` in template call.  
**Fix:** Initialize both `hn_filter_instance = None` and `hn_filter_entry_stats = None` before the conditional block.

---

## Problematiche Attuali

### 1. Short Text Scoring Bias
**Descrizione:** Testi brevi (5-10 token) ricevono punteggi artificialmente alti su entropy e TTR perché con pochi token, se tutti unici, log_TTR → 1.0 e entropy normalizzata → 1.0. Questo può portare a preferire risposte corte come hard negatives.

**Impatto:** Moderato. La soglia `len(tokens) < 3` cattura solo testi molto corti. Testi di 5-10 parole passano il filtro degenerate e possono vincere nel ranking.

**Possibile mitigazione:** Aggiungere un fattore di penalità per lunghezza minima assoluta, oppure scalare entropy/TTR per `min(1, len(tokens)/min_length)`.

### 2. Calibrazione Costosa per Dataset Grandi
**Descrizione:** `HardNegativeConfig._pipeline()` itera l'intero dataset calcolando ROUGE-L per ogni candidato contro il gold. Per dataset con milioni di sample, questo è O(N*K) dove K è il numero medio di candidati.

**Impatto:** Alto per dataset grandi. La calibrazione va fatta una volta per entry, ma con 500+ sample e 3+ candidati ciascuno, include ~1500+ chiamate ROUGE.

**Possibile mitigazione:** Sampling (calibrare su un sottoinsieme rappresentativo) o caching del config dict su disco.

### 3. `adaptive_k` Calcolato ma Non Usato
**Descrizione:** La calibrazione calcola `adaptive_k = (mean_rouge - target_rouge) / std_rouge` ma questo valore non viene poi utilizzato in `HardNegativeFilter.select()`. Sembra un placeholder per una futura feature (selezione adattiva basata sulla dimensione del pool K).

**Impatto:** Nessuno funzionalmente, ma spreco computazionale e confusione nel codice.

### 4. `_soft_norm` Ridefinita ad Ogni Iterazione
**Descrizione:** In `_rank_candidates()`, la closure `_soft_norm` viene ridefinita all'interno del loop `for cand in candidates`. Questo è un overhead minimo ma tecnicamente non necessario.

**Possibile mitigazione:** Spostare la definizione fuori dal loop.

### 5. ROUGE-L Come Unica Metrica di Similitudine
**Descrizione:** La detection di false negatives usa solo ROUGE-L. Questo cattura overlap lessicale ma non semantico — due frasi con significato identico ma parole diverse passerebbero il filtro.

**Possibile mitigazione futura:** Embedding cosine similarity (richiede un modello esterno).

---

## Proposte Future

1. **Minimum length scaling:** Penalizzare o normalizzare i punteggi per candidati con meno di N token (es. N=15)
2. **Config caching:** Salvare `config_dict` su disco dopo prima calibrazione per evitare ricalcolo
3. **Subsampling per calibrazione:** Per dataset > 10K sample, calibrare su random 2K sample
4. **Utilizzare `adaptive_k`:** Implementare selezione percentile-based all'interno del pool locale quando K > threshold
5. **Logging strutturato:** Aggiungere metriche di quanti sample vengono droppati/fallback per monitoraggio in produzione

---

## Test

```bash
python3 -m pytest tests/test_hard_negative_filtering.py -v
```

31 test cases covering:
- Helper function unit tests (entropy, TTR, percentile, text extraction)
- HardNegativeFilter unit tests (degenerate detection, false negative filtering, scoring, fallback)
- HardNegativeConfig integration tests (JSONL file, directory iteration)
- End-to-end pipeline tests (config → filter → select)
- Template integration tests (apply_chat_template with/without filter)
- prepare.py flow simulation tests (full flow matching production code path)
