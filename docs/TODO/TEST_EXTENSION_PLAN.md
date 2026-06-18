# Test Extension & Correction Plan — FineTuning-Lineage

> **Scope**: Correzioni ai test esistenti + estensione a scenari sequenziali complessi.  
> **Riferimenti**: NEW-LOG_AND_TEST_PLAN.md · Neo4j Schema · Branching Decision Matrix  
> **Versione**: 2026-06-18

---

## Parte 1 — Correzioni ai Test Esistenti

### Fix #1 · `base_experiment_id` self-reference in NEW strategy

**File**: `pre_request_handler.py`  
**Problema**: Il server risponde con `base_experiment_id: null` invece di valorizzarlo con `experiment_id` stesso.

```python
# pre_request_handler.py — handler NEW strategy
if strategy == RunStrategy.NEW and context.base is True:
    response.base_experiment_id = response.experiment_id  # self-reference
```

**Assertion da aggiornare** in `integration_new_experiment.py`:

```python
def test_new_base_experiment_id_is_self():
    ctx = client.pre_execution()
    assert ctx.strategy == "NEW"
    assert ctx.base is True
    assert ctx.base_experiment_id == ctx.experiment_id, (
        "NEW base experiment deve avere base_experiment_id == experiment_id"
    )
```

**Neo4j check atteso**:
```cypher
MATCH (e:Experiment {exp_id: $exp_id})
RETURN e.exp_id, e.base_experiment_id
// base_experiment_id deve essere uguale a exp_id
```

---

### Fix #2 · `experiment_id` mancante nelle richieste successive

**File**: `http_connector.py`  
**Problema**: Il client non passa il `experiment_id` del run precedente nei payload successivi, rompendo le catene RETRY/BRANCH/RESUME.

```python
# http_connector.py
class LineageClient:
    def __init__(self):
        self._last_experiment_id: str | None = None

    def pre_execution(
        self,
        previous_experiment_id: str | None = None,
    ) -> ExecutionContext:
        payload = PreRequestPayload(
            previous_experiment_id=previous_experiment_id or self._last_experiment_id,
            # ... resto del payload
        )
        ctx = self._post("/api/v1/pre", payload)
        self._last_experiment_id = ctx.experiment_id  # store per prossima chiamata
        return ctx
```

**Test chain RETRY** (da aggiornare in `integration_retry_experiment.py`):

```python
def test_retry_links_to_parent():
    ctx1 = client.pre_execution()
    # simula fine run
    client.post_execution(ctx1.experiment_id, status="completed")

    ctx2 = client.pre_execution(previous_experiment_id=ctx1.experiment_id)
    assert ctx2.strategy == "RETRY"
    assert ctx2.previous_experiment_id == ctx1.experiment_id
```

---

### Fix #3 · Preservazione `description` in catene RETRY

**File**: `pre_request_builder.py`

```python
def build_retry_payload(prior_ctx: ExecutionContext, config: Config) -> dict:
    return {
        "previous_experiment_id": prior_ctx.experiment_id,
        "description": prior_ctx.description or config.experiment.description,
        # ... codebase hashes
    }
```

---

### Fix #4 · Logging operazioni Neo4j (nuovo requisito)

**File**: `neo4j_logger.py` (nuovo)

Ogni operazione sul grafo deve produrre una riga di log strutturata in formato JSON-lines, separata dall'HTTP log:

```python
import logging, json
from datetime import datetime, timezone

neo4j_logger = logging.getLogger("lineage.neo4j")

def log_neo4j_op(op: str, label: str, props: dict, rel: str | None = None):
    neo4j_logger.info(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "op": op,           # CREATE_NODE | MERGE_NODE | CREATE_REL | QUERY
        "label": label,     # Experiment | Checkpoint | ...
        "rel": rel,         # DERIVED_FROM | RETRY_FROM | None
        "props": props,     # subset non-sensibile
    }))
```

Il file di log prodotto (`neo4j_ops.log`) va verificato nei test con gli stessi pattern usati per `http_communication.log`.

---

## Parte 2 — Scenari Sequenziali Estesi

Questa sezione pianifica test a più scambi che coprono le sequenze reali di utilizzo.

---

### Scenario S-01 · NEW → RETRY → RETRY (fallimento persistente)

**Descrizione**: Un esperimento base viene eseguito, poi ritentato due volte (entrambe falliscono).  
**Obiettivo**: Verificare che il grafo mostri una catena lineare `e3 -[RETRY_FROM]-> e2 -[RETRY_FROM]-> e1`.

```
[NEW]  e1 (status=failed)
         ↑ RETRY_FROM
[RETRY] e2 (status=failed)
         ↑ RETRY_FROM
[RETRY] e3 (status=failed)
```

**Passi del test** (`integration_sequences.py::test_s01_new_retry_retry`):

```python
def test_s01_new_retry_retry(client, neo4j_session):
    # Step 1 — NEW
    ctx1 = client.pre_execution()
    assert ctx1.strategy == "NEW"
    client.post_execution(ctx1.experiment_id, status="failed")

    # Step 2 — RETRY (hash identico, nessun ckp)
    ctx2 = client.pre_execution(previous_experiment_id=ctx1.experiment_id)
    assert ctx2.strategy == "RETRY"
    client.post_execution(ctx2.experiment_id, status="failed")

    # Step 3 — ancora RETRY
    ctx3 = client.pre_execution(previous_experiment_id=ctx2.experiment_id)
    assert ctx3.strategy == "RETRY"
    client.post_execution(ctx3.experiment_id, status="failed")

    # Neo4j: chain RETRY_FROM
    result = neo4j_session.run("""
        MATCH (e3:Experiment {exp_id: $e3})-[:RETRY_FROM]->(e2:Experiment)-[:RETRY_FROM]->(e1:Experiment)
        RETURN e1.exp_id, e2.exp_id, e3.exp_id
    """, e3=ctx3.experiment_id).single()
    assert result["e1.exp_id"] == ctx1.experiment_id
    assert result["e2.exp_id"] == ctx2.experiment_id

    # nessun ckp deve essere stato creato
    ckp_count = neo4j_session.run("""
        MATCH (e:Experiment)-[:PRODUCED]->(c:Checkpoint)
        WHERE e.exp_id IN $ids RETURN count(c) as n
    """, ids=[ctx1.experiment_id, ctx2.experiment_id, ctx3.experiment_id]).single()["n"]
    assert ckp_count == 0
```

---

### Scenario S-02 · NEW → BRANCH (config cambiato) → BRANCH (altro cambio)

**Descrizione**: Partendo da un esperimento base, viene modificato il config e si crea un branch; poi il branch viene a sua volta modificato, creando un secondo livello di derivazione.

```
[NEW]    e1 (base, completed)
           ↑ DERIVED_FROM {diff_patch_1}
[BRANCH] e2 (completed)
           ↑ DERIVED_FROM {diff_patch_2}
[BRANCH] e3 (running)
```

**Passi del test** (`test_s02_new_branch_branch`):

```python
def test_s02_new_branch_branch(client, neo4j_session, codebase_mutator):
    ctx1 = client.pre_execution()
    client.post_execution(ctx1.experiment_id, status="completed")

    # muta il codebase (simula cambio config/codice)
    codebase_mutator.change_config({"learning_rate": 2e-4})
    ctx2 = client.pre_execution(previous_experiment_id=ctx1.experiment_id)
    assert ctx2.strategy == "BRANCH"
    assert ctx2.diff_patch is not None
    client.post_execution(ctx2.experiment_id, status="completed")

    # seconda mutazione
    codebase_mutator.change_config({"num_epochs": 5})
    ctx3 = client.pre_execution(previous_experiment_id=ctx2.experiment_id)
    assert ctx3.strategy == "BRANCH"

    # Neo4j: path di derivazione a 2 livelli
    path = neo4j_session.run("""
        MATCH path = (e3:Experiment {exp_id: $e3})-[:DERIVED_FROM*2]->(e1:Experiment {exp_id: $e1})
        RETURN length(path) as depth
    """, e3=ctx3.experiment_id, e1=ctx1.experiment_id).single()
    assert path["depth"] == 2

    # diff_patch deve essere valorizzato su ogni relazione
    rels = neo4j_session.run("""
        MATCH (e:Experiment)-[r:DERIVED_FROM]->(parent:Experiment)
        WHERE e.exp_id IN $ids
        RETURN r.diff_patch IS NOT NULL as has_patch
    """, ids=[ctx2.experiment_id, ctx3.experiment_id]).data()
    assert all(r["has_patch"] for r in rels)
```

---

### Scenario S-03 · NEW → success + ckp → BRANCH con STARTED_FROM

**Descrizione**: Esperimento base produce checkpoint; successivamente viene creato un branch che parte fisicamente da quel checkpoint (resume field valorizzato in config.yml).

```
[NEW]    e1 ──[PRODUCED]──▶ ckp1
           ↑ DERIVED_FROM
[BRANCH] e2 ──[STARTED_FROM]──▶ ckp1
         e2 ──[PRODUCED]──▶ ckp2
```

**Passi del test** (`test_s03_branch_with_started_from`):

```python
def test_s03_branch_with_started_from(client, neo4j_session, codebase_mutator, ckp_factory):
    ctx1 = client.pre_execution()
    ckp1_id = ckp_factory.produce(ctx1.experiment_id, epoch=1, metrics={"loss": 0.42})
    client.post_execution(ctx1.experiment_id, status="completed")

    codebase_mutator.change_config({"warmup_steps": 100, "resume_from_checkpoint": ckp1_id})
    ctx2 = client.pre_execution(previous_experiment_id=ctx1.experiment_id)
    assert ctx2.strategy == "BRANCH"
    assert ctx2.started_from_checkpoint == ckp1_id

    # Neo4j: DERIVED_FROM + STARTED_FROM
    result = neo4j_session.run("""
        MATCH (e2:Experiment {exp_id: $e2})-[:DERIVED_FROM]->(e1:Experiment {exp_id: $e1})
        MATCH (e2)-[:STARTED_FROM]->(ckp:Checkpoint {id: $ckp1})
        RETURN e1.exp_id, ckp.id
    """, e2=ctx2.experiment_id, e1=ctx1.experiment_id, ckp1=ckp1_id).single()
    assert result is not None

    ckp2_id = ckp_factory.produce(ctx2.experiment_id, epoch=2, metrics={"loss": 0.31})
    client.post_execution(ctx2.experiment_id, status="completed")

    # ckp2 deve essere figlio di e2
    rel = neo4j_session.run("""
        MATCH (e:Experiment {exp_id: $e2})-[:PRODUCED]->(c:Checkpoint {id: $ckp2})
        RETURN c.id
    """, e2=ctx2.experiment_id, ckp2=ckp2_id).single()
    assert rel is not None
```

---

### Scenario S-04 · NEW → RETRY (success) → RESUME dall'ultimo ckp

**Descrizione**: Il primo tentativo fallisce, il retry ha successo e produce un checkpoint. Successivamente si vuole riprendere dall'ultimo checkpoint dello stesso esperimento.

```
[NEW]    e1 (failed) — no ckp
         ↑ RETRY_FROM
[RETRY]  e2 (completed) ──[PRODUCED]──▶ ckp2
         ↑  (stesso hash, resume=True)
[RESUME] e3 ──[STARTED_FROM]──▶ ckp2
         e3 ──[PRODUCED]──▶ ckp3
```

**Passi del test** (`test_s04_retry_then_resume`):

```python
def test_s04_retry_then_resume(client, neo4j_session, ckp_factory):
    ctx1 = client.pre_execution()
    client.post_execution(ctx1.experiment_id, status="failed")

    ctx2 = client.pre_execution(previous_experiment_id=ctx1.experiment_id)
    assert ctx2.strategy == "RETRY"
    ckp2_id = ckp_factory.produce(ctx2.experiment_id, epoch=3, metrics={"loss": 0.28})
    client.post_execution(ctx2.experiment_id, status="completed")

    # config.yml con resume=last
    ctx3 = client.pre_execution(
        previous_experiment_id=ctx2.experiment_id,
        resume_from="last",  # trigger RESUME
    )
    assert ctx3.strategy == "RESUME"
    assert ctx3.started_from_checkpoint == ckp2_id

    # Neo4j: STARTED_FROM punta all'ultimo ckp di e2
    result = neo4j_session.run("""
        MATCH (e3:Experiment {exp_id: $e3})-[:STARTED_FROM]->(ckp:Checkpoint {id: $ckp2})
        RETURN ckp.id
    """, e3=ctx3.experiment_id, ckp2=ckp2_id).single()
    assert result is not None
```

---

### Scenario S-05 · MERGE di checkpoint (intra-esperimento)

**Descrizione**: Due checkpoint prodotti dallo stesso esperimento vengono fusi tramite `merge.py`.  
Nessun nuovo `Experiment` viene creato — solo un nuovo `Checkpoint` con relazioni `MERGED_FROM`.

```
[NEW] e1 ──[PRODUCED]──▶ ckp_a
      e1 ──[PRODUCED]──▶ ckp_b
                           \   /
                        [MERGED_FROM]
                            ↓
                          ckp_merged (is_merging=False dopo merge)
```

**Passi del test** (`test_s05_intra_experiment_merge`):

```python
def test_s05_intra_experiment_merge(client, neo4j_session, ckp_factory, merge_client):
    ctx1 = client.pre_execution()
    ckp_a = ckp_factory.produce(ctx1.experiment_id, epoch=1, metrics={"loss": 0.5})
    ckp_b = ckp_factory.produce(ctx1.experiment_id, epoch=2, metrics={"loss": 0.4})
    client.post_execution(ctx1.experiment_id, status="completed")

    # merge.py eseguito — nessun training, solo fusione
    merged = merge_client.merge(
        sources=[ckp_a, ckp_b],
        experiment_id=ctx1.experiment_id,
    )
    assert merged.is_merging is False
    assert merged.is_usable is True

    # Neo4j: 2 relazioni MERGED_FROM, direzione corretta
    result = neo4j_session.run("""
        MATCH (m:Checkpoint {id: $merged})-[:MERGED_FROM]->(src:Checkpoint)
        RETURN collect(src.id) as sources
    """, merged=merged.checkpoint_id).single()
    assert set(result["sources"]) == {ckp_a, ckp_b}

    # merged NON ha PRODUCED (non è figlio di training)
    no_produced = neo4j_session.run("""
        MATCH (e:Experiment)-[:PRODUCED]->(m:Checkpoint {id: $merged})
        RETURN count(e) as n
    """, merged=merged.checkpoint_id).single()["n"]
    assert no_produced == 0
```

---

### Scenario S-06 · MERGE inter-esperimento + PROMOTED_TO Model

**Descrizione**: Due checkpoint da esperimenti diversi vengono fusi e il risultato viene promosso a `Model` (adapter).

```
e1 ──[PRODUCED]──▶ ckp1
e2 ──[PRODUCED]──▶ ckp2
                    \  /
               [MERGED_FROM]
                    ↓
                ckp_merged ──[PROMOTED_TO]──▶ :Model {type: "adapter"}
```

**Passi del test** (`test_s06_inter_experiment_merge_and_promote`):

```python
def test_s06_inter_experiment_merge_and_promote(client, neo4j_session, ckp_factory, merge_client):
    ctx1 = client.pre_execution()
    ckp1 = ckp_factory.produce(ctx1.experiment_id, epoch=2)
    client.post_execution(ctx1.experiment_id, status="completed")

    # branch separato
    ctx2 = client.pre_execution()  # NEW separato (altro modello o recipe)
    ckp2 = ckp_factory.produce(ctx2.experiment_id, epoch=2)
    client.post_execution(ctx2.experiment_id, status="completed")

    merged = merge_client.merge(sources=[ckp1, ckp2])
    model_id = merge_client.promote(merged.checkpoint_id, model_name="merged-llama-7b-adapter")

    # Neo4j: PROMOTED_TO + tipo adapter
    result = neo4j_session.run("""
        MATCH (ckp:Checkpoint {id: $ckp})-[:PROMOTED_TO]->(m:Model {model_name: $name})
        RETURN m.type
    """, ckp=merged.checkpoint_id, name="merged-llama-7b-adapter").single()
    assert result["m.type"] == "adapter"
```

---

### Scenario S-07 · Albero completo: NEW → BRANCH → RETRY → RESUME

**Descrizione**: Sequenza realistica a 4 esperimenti che tocca tutti e 4 i path della matrice decisionale.

```
[NEW]    e1 (completed) ──[PRODUCED]──▶ ckp1
           ↑ DERIVED_FROM
[BRANCH] e2 (failed) — no ckp
           ↑ RETRY_FROM
[RETRY]  e3 (completed) ──[PRODUCED]──▶ ckp2
           ↑ (stesso hash, resume=last)
[RESUME] e4 ──[STARTED_FROM]──▶ ckp2
```

**Passi del test** (`test_s07_full_tree`):

```python
def test_s07_full_tree(client, neo4j_session, ckp_factory, codebase_mutator):
    # NEW
    ctx1 = client.pre_execution()
    assert ctx1.strategy == "NEW"
    ckp1 = ckp_factory.produce(ctx1.experiment_id, epoch=1)
    client.post_execution(ctx1.experiment_id, status="completed")

    # BRANCH (modifica config)
    codebase_mutator.change_config({"lr_scheduler": "cosine"})
    ctx2 = client.pre_execution(previous_experiment_id=ctx1.experiment_id)
    assert ctx2.strategy == "BRANCH"
    client.post_execution(ctx2.experiment_id, status="failed")

    # RETRY (stessa modifica, retry)
    ctx3 = client.pre_execution(previous_experiment_id=ctx2.experiment_id)
    assert ctx3.strategy == "RETRY"
    ckp2 = ckp_factory.produce(ctx3.experiment_id, epoch=2)
    client.post_execution(ctx3.experiment_id, status="completed")

    # RESUME (dall'ultimo ckp di e3)
    ctx4 = client.pre_execution(
        previous_experiment_id=ctx3.experiment_id,
        resume_from="last",
    )
    assert ctx4.strategy == "RESUME"
    assert ctx4.started_from_checkpoint == ckp2

    # Neo4j: verifica struttura completa
    # 1. catena di derivazione
    chain = neo4j_session.run("""
        MATCH (e4:Experiment {exp_id: $e4})-[:RETRY_FROM]->(e3)-[:RETRY_FROM*0..]->(x)
        RETURN collect(x.exp_id) as chain
    """, e4=ctx4.experiment_id).single()

    # 2. DERIVED_FROM e1←e2
    derived = neo4j_session.run("""
        MATCH (e2:Experiment {exp_id: $e2})-[:DERIVED_FROM]->(e1:Experiment {exp_id: $e1})
        RETURN e1.exp_id
    """, e2=ctx2.experiment_id, e1=ctx1.experiment_id).single()
    assert derived is not None

    # 3. STARTED_FROM
    resume_rel = neo4j_session.run("""
        MATCH (e4:Experiment {exp_id: $e4})-[:STARTED_FROM]->(ckp:Checkpoint {id: $ckp2})
        RETURN ckp.id
    """, e4=ctx4.experiment_id, ckp2=ckp2).single()
    assert resume_rel is not None

    # 4. no circular deps
    circular = neo4j_session.run("""
        MATCH path = (e:Experiment)-[:DERIVED_FROM|RETRY_FROM*]->(e)
        RETURN COUNT(path) AS n
    """).single()["n"]
    assert circular == 0
```

---

## Parte 3 — Neo4j Test Strategy

### Opzioni di Setup

| Opzione | Requisiti | Pro | Contro |
|---------|-----------|-----|--------|
| **Neo4j Embedded** (`neo4j-driver` + `testcontainers`) | Docker locale | Reale, zero mock | Richiede Docker |
| **`neo4j-driver` + mock session** | Solo Python | Veloce, CI-friendly | Non testa Cypher reale |
| **Neo4j AuraDB Free** | Account cloud | Nessun Docker | Latenza, rate limit |

**Raccomandazione**: usare `testcontainers-python` con `neo4j:5-community` per integration test; mock session per unit test rapidi.

```python
# conftest.py
import pytest
from testcontainers.neo4j import Neo4jContainer

@pytest.fixture(scope="session")
def neo4j_container():
    with Neo4jContainer("neo4j:5-community").with_env("NEO4J_AUTH", "neo4j/testpass") as neo4j:
        yield neo4j

@pytest.fixture
def neo4j_session(neo4j_container):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        neo4j_container.get_connection_url(),
        auth=("neo4j", "testpass"),
    )
    with driver.session() as session:
        yield session
    driver.close()
```

> **Nota**: Se non hai Docker disponibile segnalacelo — i test possono essere scritti con un `MockNeo4jSession` che intercetta le query Cypher e restituisce stub, rimandando la validazione reale a un ambiente CI.

---

### Neo4j Operations Log — Formato

Ogni operazione deve produrre una riga in `neo4j_ops.jsonl`:

```jsonc
// CREATE nodo Experiment
{"ts":"2026-06-18T10:00:00Z","op":"MERGE_NODE","label":"Experiment","props":{"exp_id":"e-001","status":"running"}}
// CREATE relazione
{"ts":"2026-06-18T10:00:01Z","op":"CREATE_REL","label":"RETRY_FROM","from":"e-002","to":"e-001"}
// QUERY linee
{"ts":"2026-06-18T10:00:02Z","op":"QUERY","cypher":"MATCH (e:Experiment)-[:RETRY_FROM*]...", "rows":3}
```

**Test di validazione del log**:

```python
def test_neo4j_log_has_create_rel_for_retry(neo4j_log_reader, ctx1, ctx2):
    ops = neo4j_log_reader.filter(op="CREATE_REL", label="RETRY_FROM")
    assert any(
        o["from"] == ctx2.experiment_id and o["to"] == ctx1.experiment_id
        for o in ops
    )
```

---

## Parte 4 — Matrice di Copertura Post-Estensione

| Test | Strategy | Relazioni Neo4j verificate | Log HTTP | Log Neo4j |
|------|----------|---------------------------|----------|-----------|
| Fix #1 | NEW | `base_experiment_id == exp_id` | ✅ | ✅ |
| Fix #2 | RETRY/BRANCH/RESUME | catena `previous_experiment_id` | ✅ | — |
| S-01 | NEW→RETRY→RETRY | `RETRY_FROM` × 2 | ✅ | ✅ |
| S-02 | NEW→BRANCH→BRANCH | `DERIVED_FROM` × 2 + `diff_patch` | ✅ | ✅ |
| S-03 | NEW→BRANCH+ckp | `DERIVED_FROM` + `STARTED_FROM` | ✅ | ✅ |
| S-04 | NEW→RETRY→RESUME | `RETRY_FROM` + `STARTED_FROM` | ✅ | ✅ |
| S-05 | MERGE intra-exp | `MERGED_FROM` × 2, no `PRODUCED` | — | ✅ |
| S-06 | MERGE + PROMOTED_TO | `MERGED_FROM` + `PROMOTED_TO` | — | ✅ |
| S-07 | Full tree (4 exp) | tutte le relazioni + no-circular check | ✅ | ✅ |

---

## Parte 5 — Roadmap di Implementazione

### Sprint 1 — Correzioni bloccanti (2–3h)
1. `pre_request_handler.py` → Fix #1 (base_experiment_id self-ref)
2. `http_connector.py` → Fix #2 (pass previous experiment_id)
3. `pre_request_builder.py` → Fix #3 (description preservation)
4. Update assertions in test esistenti (integration_new/retry/branch/resume)

### Sprint 2 — Neo4j logging (1–2h)
5. `neo4j_logger.py` → implementazione log strutturato
6. Integrazione nel repository handler (ogni MERGE/CREATE/QUERY loggato)
7. `conftest.py` → setup testcontainers Neo4j fixture

### Sprint 3 — Scenari sequenziali (3–4h)
8. `integration_sequences.py` → S-01, S-02, S-03, S-04
9. `integration_merge.py` (fix + extend) → S-05, S-06
10. `integration_full_tree.py` → S-07

### Sprint 4 — Validazione log (1h)
11. `test_neo4j_log_validation.py` → verifica neo4j_ops.jsonl per ogni scenario
12. Aggiornare `test_http_logging_demo.py` con asserzioni catene multi-step

---

## Note Finali

- Le query Cypher di verifica negli scenari S-01…S-07 sono progettate per essere eseguite sia su Neo4j reale (testcontainers) sia su mock; la differenza sta solo nella fixture `neo4j_session`.
- Il controllo anti-circular (`MATCH path = (e)-[:DERIVED_FROM|RETRY_FROM*]->(e) RETURN COUNT(path)`) va aggiunto come assertion globale in **tutti** gli scenari sequenziali, non solo S-07.
- La relazione `MERGED_FROM` ha direzione `merged_ckp → source_ckp` — non invertire mai nei test.
- `is_merging=True` è uno stato transitorio: va verificato durante la creazione e poi `False` a merge completato (vedi S-05).
