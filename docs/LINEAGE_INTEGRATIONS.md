# LINEAGE_INTEGRATIONS — Metadata Design per Agentic Researcher

## Filosofia di design

Lo schema esistente tratta l'esperimento come un **record di training**. Per un agente researcher autonomo, ogni esperimento deve diventare un **nodo epistemico**: non solo "cosa è successo" ma "cosa si è imparato, perché vale la pena esplorare questa direzione, e cosa blocca il progresso".

L'agente deve poter fare due tipi di query fondamentalmente diversi:

- **Verificare** → "Questo config ha già prodotto risultati usabili?"
- **Esplorare** → "Quali direzioni di ricerca sono ancora aperte? Dove si concentrano i successi? Cosa non ho ancora tentato?"

---

## Architettura dei metadati: backend vs UI

Il backend (worker YAML + nodo Neo4j) mantiene il **principio di minimalità**: registra solo ciò che è oggettivamente misurabile o necessario all'esecuzione.

I metadati agentici descritti in questo documento — `hypothesis`, `conclusion`, `evidences`, `open_questions` e gli altri — sono **metadati epistemici** che l'agente (o un ricercatore umano) compila tramite una **UI dedicata connessa direttamente al DB**. La UI espone un form strutturato per ogni nodo `:Experiment`, con campi tipizzati, enum dropdown, e validazione lato client. Questo approccio:

- Mantiene il backend snello e privo di dipendenze dall'interpretazione umana/agente
- Permette di aggiornare i metadati **post-run**, quando i risultati sono disponibili
- Consente all'agente di scrivere autonomamente sul grafo via API Neo4j senza toccare il sistema di training
- Separa nettamente il piano dell'**esecuzione** da quello della **conoscenza**

---

## Nuovi campi proposti per `:Experiment`

### Gruppo 1 — Identità e contesto della ricerca

| Campo | Tipo | Descrizione |
|---|---|---|
| `scope` | string enum | Macro-categoria dell'esperimento: `"baseline"`, `"ablation"`, `"hyperparameter_search"`, `"architecture_change"`, `"data_experiment"`, `"regression_check"` |
| `hypothesis` | string | Ipotesi esplicita che l'agente stava testando quando ha lanciato l'esperimento: *"Aumentare il learning rate di 10x su questo dataset dovrebbe ridurre il loss del 5%"*. Compilato **prima** del run, non dopo. |
| `motivation` | string | Perché questo esperimento esiste: quale osservazione su un esperimento precedente lo ha motivato. Distinto da `description` (che descrive *cosa fa*) e `hypothesis` (che predice *cosa succederà*). |

---

### Gruppo 2 — Conoscenza estratta post-run

| Campo | Tipo | Descrizione |
|---|---|---|
| `conclusion` | string | Sintesi dell'agente al termine del run: cosa ha effettivamente imparato, indipendentemente dal successo. Un run fallito con buona conclusion è **prezioso**. |
| `conclusion_type` | string enum | Categorizza l'esito epistemico: `"confirmed"` (ipotesi validata), `"refuted"` (ipotesi smentita), `"inconclusive"` (dati insufficienti), `"unexpected"` (scoperta non prevista), `"error"` (run non valido per ragioni tecniche) |
| `evidences` | JSON array | Lista strutturata di metriche o osservazioni che supportano la conclusion. Es: `[{"metric": "eval_loss", "value": 0.18, "delta_vs_baseline": -0.05, "significant": true}]`. Separa i fatti grezzi dall'interpretazione contenuta in `conclusion`. |
| `open_questions` | JSON array | Domande che questo esperimento ha generato ma non risposto. Alimenta direttamente la coda di esplorazione dell'agente. Es: `["Does this hold with 13B?", "Is improvement dataset-specific?"]` |

---

### Gruppo 3 — Navigabilità del grafo (per query di esplorazione)

| Campo | Tipo | Descrizione |
|---|---|---|
| `usable` | bool | **Già presente nel backend.** Flag binario: questo nodo è un risultato affidabile su cui costruire. Permette di potare interi sottoalberi. |
| `is_base` | bool | **Già in YAML come `base`.** Marca gli esperimenti di riferimento da cui si parte. Consente query tipo *"dammi tutti i baseline e i loro discendenti diretti"*. |
| `exploration_priority` | float [0-1] | Score assegnato dall'agente **al momento della creazione** per indicare quanto ritiene promettente questa direzione. Utile per ricostruire retrospettivamente la strategia di ricerca. |
| `dead_end` | bool | Flag esplicito: questa direzione non vale la pena esplorare ulteriormente. Distinto da `usable=false` (che indica un run tecnico fallito) — un run completato può essere `usable=true` ma `dead_end=true` se la direzione si è dimostrata sterile. |
| `tags` | string array | Label libere per clustering semantico rapido: `["low-lr", "no-warmup", "long-context", "dataset-v2"]`. Permettono query tipo *"tutti gli esperimenti sul dataset-v2 non dead-end"* senza dover parsare JSON. |

---

### Gruppo 4 — Riproducibilità e affidabilità

| Campo | Tipo | Descrizione |
|---|---|---|
| `confidence` | float [0-1] | Quanto l'agente si fida del risultato: tiene conto di varianza tra retry, qualità dei dati, stabilità del training. Distinto dal valore delle metriche — un run con ottimo loss ma alta varianza ha bassa confidence. |
| `retry_policy` | string enum | Indica se e come questo esperimento dovrebbe essere rieseguito: `"none"`, `"on_failure"`, `"always"` (per baseline), `"if_promising"`. Aiuta l'agente a decidere autonomamente se fare retry. |
| `validation_scope` | string enum | Granularità della valutazione: `"train_only"`, `"held_out"`, `"full_benchmark"`, `"human_eval"`. Fondamentale per confrontare esperimenti: due run con stesso loss ma diversa `validation_scope` non sono comparabili. |

---

### Gruppo 5 — Metadati computazionali (per cost-aware exploration)

| Campo | Tipo | Descrizione |
|---|---|---|
| `compute_cost` | float | Costo stimato in ore-GPU o token equivalenti. Permette all'agente di fare **cost-benefit** prima di esplorare una direzione: *"questa ablation costa 10x il baseline, ne vale la pena?"* |
| `duration_seconds` | int | Durata effettiva del run. Distinto dal costo teorico — utile per pianificare finestre di esecuzione. |
| `estimated_gain` | float | Delta atteso sulla metrica principale, stimato **prima** del run. Confrontato con il delta reale in `evidences`, misura la **calibrazione predittiva** dell'agente nel tempo. |

---

## Nodo `:Experiment` completo (backend + metadati UI)

```cypher
CREATE (e:Experiment {
    -- BACKEND: compilati dal worker al momento del run --
    id: $id,
    exp_id: $exp_id,
    model_id: $model_id,
    status: $status,
    description: $description,
    created_at: $created_at,
    updated_at: $updated_at,
    usable: true,

    -- METADATI AGENTICI: compilati tramite UI o dall'agente post-run --

    -- Gruppo 1: Identità e contesto
    scope: null,
    hypothesis: null,
    motivation: null,

    -- Gruppo 2: Conoscenza estratta
    conclusion: null,
    conclusion_type: null,
    evidences: null,
    open_questions: null,

    -- Gruppo 3: Navigabilità
    is_base: false,
    exploration_priority: null,
    dead_end: false,
    tags: [],

    -- Gruppo 4: Affidabilità
    confidence: null,
    retry_policy: "on_failure",
    validation_scope: null,

    -- Gruppo 5: Costi
    compute_cost: null,
    duration_seconds: null,
    estimated_gain: null
})
```

> I campi `null` al momento della creazione vengono popolati dalla UI o dall'agente
> tramite `SET` successivi. I trigger APOC esistenti gestiranno automaticamente `updated_at`.

---

## Pattern di query agentici abilitati

### Esplorazione rapida delle direzioni aperte
```cypher
MATCH (e:Experiment)
WHERE e.dead_end = false AND e.usable = true
AND NOT (e)<-[:DERIVED_FROM]-(:Experiment)
RETURN e.exp_id, e.conclusion, e.open_questions, e.tags
ORDER BY e.exploration_priority DESC
```
*"Dammi i leaf node promettenti: dove non ho ancora esplorato?"*

---

### Ricostruzione della narrativa di ricerca
```cypher
MATCH path = (base:Experiment {is_base: true})-[:DERIVED_FROM*]->(leaf:Experiment)
WHERE leaf.usable = true
RETURN [n IN nodes(path) | {
    id: n.exp_id,
    hypothesis: n.hypothesis,
    conclusion: n.conclusion,
    conclusion_type: n.conclusion_type
}] AS research_story
```
*"Raccontami come siamo arrivati qui: ipotesi per ipotesi."*

---

### Individuare sorprese non ancora sfruttate
```cypher
MATCH (e:Experiment {conclusion_type: "unexpected"})
WHERE NOT (e)<-[:DERIVED_FROM]-(:Experiment)
RETURN e.exp_id, e.conclusion, e.open_questions
```
*"Ci sono scoperte inattese che nessuno ha ancora approfondito?"*

---

### Cost-benefit per la prossima mossa
```cypher
MATCH (e:Experiment)
WHERE e.dead_end = false AND e.usable = true
  AND e.estimated_gain IS NOT NULL AND e.compute_cost IS NOT NULL
WITH e, (e.estimated_gain - coalesce(e.confidence, 0.5)) / e.compute_cost AS roi
RETURN e.exp_id, e.hypothesis, roi
ORDER BY roi DESC LIMIT 5
```
*"Quali direzioni hanno il miglior rapporto tra gain atteso e costo?"*

---

### Potatura del grafo: eliminare i percorsi sterili
```cypher
MATCH path = (root:Experiment)-[:DERIVED_FROM*]->(leaf:Experiment)
WHERE ALL(n IN nodes(path) WHERE n.usable = true AND n.dead_end = false)
RETURN path
```
*"Mostami solo i percorsi di ricerca che sono rimasti vivi dall'inizio alla fine."*

---

### Calibrazione predittiva dell'agente nel tempo
```cypher
MATCH (e:Experiment)
WHERE e.estimated_gain IS NOT NULL AND e.evidences IS NOT NULL
WITH e,
     e.estimated_gain AS predicted,
     [ev IN e.evidences WHERE ev.significant = true | ev.delta_vs_baseline][0] AS actual
RETURN e.exp_id, predicted, actual, abs(predicted - actual) AS prediction_error
ORDER BY e.created_at ASC
```
*"L'agente sta migliorando nelle sue previsioni nel tempo?"*

---

## Distinzioni chiave da tenere a mente

| Coppia | Differenza |
|---|---|
| `description` vs `hypothesis` vs `motivation` | **description**: cosa fa (backend). **motivation**: perché esiste, quale osservazione passata lo ha generato. **hypothesis**: claim verificabile su cosa succederà. |
| `usable` vs `dead_end` | **usable=false**: run tecnico non valido, non fidarsi dei risultati. **dead_end=true**: run valido, ma la direzione è sterile — non esplorare ulteriormente. Un nodo può essere `usable=true, dead_end=true`. |
| `conclusion` vs `evidences` | **evidences**: fatti grezzi misurati (JSON strutturato). **conclusion**: interpretazione dell'agente in linguaggio naturale. Separare i dati dall'opinione è critico per query e audit. |
| `exploration_priority` vs `confidence` | **exploration_priority**: quanto vale la pena esplorare *questa direzione*. **confidence**: quanto ci fidiamo *di questo risultato specifico*. Possono divergere: alta priority, bassa confidence = direzione promettente ma risultato rumoroso, fare retry. |
| `estimated_gain` vs `evidences[].delta_vs_baseline` | **estimated_gain**: previsione pre-run dell'agente. **delta_vs_baseline**: misurazione reale post-run. Il confronto tra i due è la misura della qualità dell'agente come researcher. |
