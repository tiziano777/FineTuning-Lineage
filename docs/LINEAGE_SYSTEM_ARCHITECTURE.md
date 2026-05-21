# AI Experiment Lineage System — Architecture & Implementation Guide

> **SCOPE** progettazione, implementazione e integrazione del sistema di tracciamento del lineage di esperimenti AI.

---

## 1. Visione d'insieme

### 1.1 Contesto

Dobbiamo creare un plugin simile a un tracer, ma invece di essere passivo e raccogliere i risultati in log, deve poter prendere decisioni in base allo stato della codebase.

#### 1.1.1 collega esperiemento
Quando abbiamo una codebase funzionante che riesce a eseguire il train senza generare errori, allora possiamo collegare il nostro plug-in come se fosse un hook.

#### 1.1.2 Esegui runs
Idealmente vorremmo hook in-code agganciato al main o al processo principale, una volta eseguito il file, prima di eseguire la routine, ssi fa verifica di cambiamenti nella codebase, in base ai cambiamenti, si prendono decisioni per fare update specifico su un DB neo4j.

#### 1.1.3 Casi d'uso
Ci sono vari casi che tracciamo:
- RUN identica alla precedente, nessun file critico cambiato --> RETRY
- RUN con cambio di parametri o logica di train/prepare o altri moduli --> BRANCHING
- RUN specifica che esegue merge.py su dei CKP o CKP su MODEL --> MERGING
- RUN che riparte da un CKP specifico --> STARTED_FROM

NOTA, alcune operazioni come merging e started from saranno triggerate da alcuni compi nel config.yml che daranno sia informatività sia activation.

Obiettivi:

- Registrare ogni esperimento, checkpoint e relazione di derivazione tra esperiementi in un grafo Neo4j come un hook capace di eseguire operazioni prima di esecuzione della run di train, e raccoglire risultato (FAILED, SUCCESS... )
- Deve funzionare ANCHE su macchine fisicamente separate (GPU worker ↔ DB master) con comunicazione asincrona e sincrona.
- UI integrata, per navigazione degli esperimenti e naigazione delle history 

## 2. Struttura del Progetto da Tracciare

```
<base_experiment_folder_name>/
├── __init__.py          # pr import dei custom modules
├── modules/             # ABC and utils and so far
├── prepare.py           # file that process data and flush into .cache/
├── train.py             # train file ,read from .cache/ and start training
├── merge.py             # optional, used for particular merge operations
├── requirements.txt     # requirements
├── .cache/              # ignored, prepare.py write data, train.py retrive data
├── .venv/               # ignored
└── config.yml           # Unified configuration file, used as state tracking also
```

## 3. Data Model — Neo4j Graph Schema

### 3.1 Nodi

#### `Recipe`
Punto di ingresso di ogni esperimento. Contiene la configurazione dichiarativa. Definito come **BaseModel** Pydantic per coerenza con tutti gli altri nodi.

```python
from .base import BaseEntity

class RecipeEntry(BaseModel):
    """Metadata for a single distribution/dataset entry in a recipe."""

    chat_type: str = Field(..., min_length=1, description="Chat conversation type")
    dist_id: str = Field(..., min_length=1, description="Distribution unique identifier")
    dist_name: str = Field(..., min_length=1, description="Human-readable distribution name")
    dist_uri: str = Field(..., min_length=1, description="Path or URI to distribution")
    replica: int = Field(1, ge=1, description="Replication factor (N× oversampling)")
    samples: int = Field(..., gt=0, description="Total number of samples in distribution")
    system_prompt: list[str] | None = Field(None, description="System prompt templates")
    system_prompt_name: list[str] | None = Field(None, description="System prompt names")
    tokens: int = Field(..., gt=0, description="Total token count")
    words: int = Field(..., gt=0, description="Total word count")
    validation_error: str | None = Field(None, description="Validation error if any")

class Recipe(BaseEntity):
    """Configuration for recipe/distribution metadata.

    Maps dataset paths to their metadata entries with optional scope, tasks, tags, and derived_from.

    Note:
        name can be None at parse time (recipe from YAML without 'name' field).
        Use ensure_name(filename) to derive name from filename before persistence.
        Filename format: "my_recipe.yaml" → "my_recipe"
    """

    name: str  = Field(None, min_length=1, description="Recipe name (must be unique)")
    description: str | None = Field(None, description="Recipe description")
    scope: str | None = Field(None, description="Scope for this recipe (e.g., 'sft', 'preference', 'rl')")
    tasks: list[str] = Field(default_factory=list, description="Tasks associated with this recipe")
    tags: list[str] = Field(default_factory=list, description="Tags for categorizing recipes")
    derived_from: str | None = Field(None, description="Optional UUID of parent recipe this was derived from")
    entries: dict[str, RecipeEntry] = Field(
        ...,
        description="Mapping of dataset paths to distribution metadata"
    )
```

Il file recipe da uploadare contiene uno snapshot delle location dei vari datasets, con relative info su replica e altri metadati:

```yaml
id: ee81b902-7672-4253-8326-4f870bea10f5
name: r1
description: r1
scope: ...
task: []
tags: []
derived_from: uuid
entries:
  /path/to/dataset/ARC-Challenge/en:
    dist_id: a9a55ac3-e220-480d-a06e-cc4005960414
    dist_name: mapped__ARC-Challenge__en
    dist_uri: /path/to/dataset/ARC-Challenge/en
    tokenized_uri: null
    chat_type: context_chat
    system_prompt: &id001 []
    system_prompt_name: &id002 []
    replica: 1
    samples: 2590
    tokens: 179178
    words: 129464
    validation_error: null
```

#### Other Nodes

Check in @data_classes/neo4j/nodes

### 3.2 Relazioni

```
(Component)  -[:USED_FOR]→     (Experiment)    # Stack tecnologico usato
(Model)      -[:SELECTED_FOR]→ (Experiment)    # Modello base selezionato
(Experiment) -[:BASED_ON]→     (Recipe)        # Configurazione di input
(Experiment) -[:PRODUCED]→     (Checkpoint)    # Checkpoint generato

(Experiment) -[:DERIVED_FROM {diff_patch: JSON}]→ (Experiment)   # Branching logico
(Experiment) -[:STARTED_FROM]→                    (Checkpoint)   # Branching fisico (opz.)
(Experiment) -[:RETRY_OF]→                        (Experiment)   # Stesso setup, nuovo tentativo

(Checkpoint) -[:MERGED_FROM]→  (Checkpoint)    # Merge N-a-1 di pesi
(Checkpoint) -[:PROMOTED_TO]→  (Model)    # with kind == ADAPTER
(Model) -[:MERGED_FROM]→  (Model)    # Merge N-a-1 di pesi dei modelli, sia Adapter che modelli base che richiedono fusione con adapters.
```

NOTA: per il finetuning abbiamo applicato convenzione che ignora il model merging di modelli base, i nostri ckp produrranno tutti adapters.

#### Proprietà della relazione `DERIVED_FROM`

Il campo `diff_patch` contiene il diff git-style completo tra i file dell'experiment precedente e quello nuovo.

- Abiamo intenzione di usare un diffPatcher specifico, ovvero `diff_match_patch`



### 3.3 Constraints e Indici Neo4j

```cypher
CREATE CONSTRAINT recipe_id     IF NOT EXISTS FOR (r:Recipe)     REQUIRE r.recipe_id IS UNIQUE;
CREATE CONSTRAINT name     IF NOT EXISTS FOR (r:Recipe)     REQUIRE r.name IS UNIQUE;
CREATE CONSTRAINT experiment_id IF NOT EXISTS FOR (e:Experiment) REQUIRE e.exp_id IS UNIQUE;
CREATE CONSTRAINT checkpoint_id IF NOT EXISTS FOR (c:Checkpoint) REQUIRE c.ckp_id IS UNIQUE;
CREATE CONSTRAINT model_name    IF NOT EXISTS FOR (m:Model)      REQUIRE m.model_name IS UNIQUE;
CREATE CONSTRAINT component_composite IF NOT EXISTS FOR (c:Component) REQUIRE (c.technique_code, c.framework_code) IS UNIQUE;
```

### 3.4 APOC Triggers

**Timestamp automatico** (created_at / updated_at):

```cypher
CALL apoc.trigger.install('neo4j', 'setNodeTimestamps', '
  UNWIND $createdNodes AS n
  SET n.created_at = coalesce(n.created_at, datetime()),
      n.updated_at = coalesce(n.updated_at, datetime())
  UNION ALL
  UNWIND keys($assignedNodeProperties) AS key
  UNWIND $assignedNodeProperties[key] AS map
  WITH map.node AS node, collect(map.key) AS propList
  WHERE NOT "updated_at" IN propList
  SET node.updated_at = datetime()
', {phase: "before"});
```

**Validation guard** (Checkpoint orfano — con eccezione per merge):

```cypher
CALL apoc.trigger.install('neo4j', 'validateCheckpointHasExperiment', '
  UNWIND $createdNodes AS n
  WITH n WHERE "Checkpoint" IN labels(n) AND NOT coalesce(n.is_merging, false)
  CALL apoc.util.validate(
    NOT EXISTS { MATCH (e:Experiment)-[:PRODUCED]->(n) },
    "Checkpoint %s must have a PRODUCED relationship from an Experiment (or is_merging=true for merged checkpoints)",
    [n.ckp_id]
  )
  RETURN n
', {phase: "before"});
```

**Nota**: Il trigger esclude i checkpoint con `is_merging = true` (flag che indica partecipazione a operazione di merge), permettendo ai checkpoint merged di esistere senza relazione `PRODUCED` diretta da un esperimento attivo.

> **⚠️ Agent Note**: I trigger APOC richiedono che il plugin APOC sia installato e che `apoc.trigger.enabled=true` sia nella configurazione Neo4j. Verificare nel `docker-compose.yml` prima di eseguire lo schema.

---

## 4. Logica di Branching e Casistiche

### 4.1 Matrice Decisionale 

| Hash identico | Checkpoint richiesto | Strategia | 
|---------------|---------------------|-----------|
| ✅ | ✅ (ultimo ckp) | **RESUME** | 
| ✅ | ❌ | **RETRY** | Crea nuovo `Experiment` + `RETRY_OF` |
| ❌ | ✅ | **BRANCH** | Crea nuovo `Experiment` + `DERIVED_FROM` + `STARTED_FROM` |
| ❌ | ❌ | **NEW** | Crea nuovo `Experiment` isolato, questa è la prima opearazione che crea un solo Nodo come BASE_* |

### 4.2 Caso: RESUME (Continuità)

**Trigger**: Il Worker invia lo stesso hash della codebase, ma non in config.yml e chiede di ripartire dall'ultimo checkpoint della stessa run, grazie a un campo nel config.yml, sappiamo da quale ckp partire, e creaimo nuovo esperimento che genererà nuovi ckp o fallirà tornando un messaggio di errore.


### 4.3 Caso: BRANCH (Cambio Traiettoria)

**Trigger**: Hash del config e/o della codebase diverso rispetto all'esperimento precedente.

**Due subcasi**:

1. **BRANCH con Checkpoint di partenza** (resume field nuovo fornito):
   - Master crea nuovo `Experiment`.
   - Lega con `DERIVED_FROM {diff_patch}` all'esperimento precedente.
   - Lega con `STARTED_FROM` al checkpoint fisico di partenza.
   - I pesi vengono caricati dal checkpoint (non da zero).

2. **BRANCH senza Checkpoint** ( resume field None o unchanged) — opzione: cambio configurazione ripartendo da zero o dal modello base:
   - Master crea nuovo `Experiment`.
   - Lega con `DERIVED_FROM {diff_patch}` all'esperimento precedente.
   - **NON** crea `STARTED_FROM` (non abbiamo checkpoint source).
   - Allineamento logico: il nuovo esperimento è una derivazione del precedente, ma i pesi non vengono ereditati— il training ricomincia dal modello base o dal ckp del vecchio esperimento.

### 4.4 Caso: RETRY (Nuovo Tentativo)

**Trigger**: Hash identico, nessun checkpoint di partenza (start from zero).

**Comportamento**: Crea nuovo `Experiment` legato al precedente con `RETRY_OF`. Preserva lo storico dei fallimenti senza contaminare i nuovi dati.

### 4.5 Caso: MERGING (Fusione di Pesi)

**Trigger**: L'utente richiede di fondere N checkpoint (inter o intra esperimento) tramite un field in config.yml e annessa lista di ckps or models.

**Comportamento**:
1. Script `merge.py` based on `mergekit` sui checkpoint sorgente.
3. Se l'esecuzione riesce: crea nuovo `Checkpoint` con N relazioni `MERGED_FROM` con i suoi ckp padre.
4. Il nuovo checkpoint non è necessariamente figlio di un `PRODUCED` (può esistere senza training attivo).

> **⚠️ Agent Note**: La relazione `MERGED_FROM` va da `new_ckp → source_ckp` (direzione: "è stato creato da"). Non invertire la direzione.

---

## 5. Criticità e Soluzioni Architetturali

### 5.1 Checkpoint Eliminati (`uri = NULL`)

**Problema**: Checkpoint scartato per risparmio spazio (solo metriche preservate).

**Soluzione**:
- if not resolved URI -> SET  `uri = NULL` and return a specific exit code/msg.
- Il nodo `Checkpoint` esiste nel grafo (coerenza storica del lineage).
- La UI disabilita "Resume" e "Download" per nodi con `uri = NULL`.
- Le metriche sono comunque accessibili in un mount specifico

### 5.2 Server depedent architecture

**Problema**: Worker (GPU train) e Master (sistema che salva lineage) possono essere macchine separate, necessitano di metodi di connessione, e ovviamente che il middleware possa inviare gli update attrverso essa

**Soluzione**:
- Hook cattura e invia lineage, bisogna però definire una classe base + estensioni per supportare connesisioni (ssh, tcp, http..)
-  e un protocollo API in modo che middleware di observability lineage possa inviare le modifiche ikn automatico. (CRUD operation on neo4j graph!) 


### 5.3 Inconsistenza dei Path URI

**Problema**: I riusltati HW e metrics del train son salvate su disco, dobbiamo referenziarle come metadati per fare retrieve quando serve, o iniviarle come copia sul master (server machine).

**Soluzione**: 
- astrarre nella maniera piu semplice possibile qualsiasi URI, crea un file apposito che identifica PREFIX+URI in modo da eseguire ogni perazione indipendentemente della posizione del disco e della macchina.
- Quando e se training finisce o viene interrotto producendo dati, questi vanno flushati sul disco del server se il server non puo raggiungerli.


### 5.4 Checkpoint Orfani

**Problema**: Un `Checkpoint` creato senza la relazione `PRODUCED` dal suo `Experiment`.

**Soluzione**: APOC trigger `validateCheckpointHasExperiment` (fase `before`) rifiuta la transazione se il constraint è violato. Eccezione: i checkpoint prodotti da `MERGED_FROM` non hanno necessariamente un `PRODUCED` diretto da un Experiment attivo — il trigger deve gestire questo caso.

> **⚠️ Agent Note**: Il trigger di validazione deve avere un'eccezione per i checkpoint con `is_merging = true`. Aggiustare il Cypher di conseguenza.

### 5.5 Relazioni Circolari nel Grafo

**Problema**: Un `Experiment` potrebbe accidentalmente derivare da sé stesso.

**Soluzione**: `ConsistencyGuard` nel Master valida che `source_exp_id != target_exp_id` in `DERIVED_FROM` e `RETRY_OF`. Aggiungere anche un check di profondità massima (es. max 50 livelli di derivazione) per prevenire query ricorsive illimitate.

### 5.6 Assenza di Trigger Nativi Neo4j

Neo4j non ha trigger nativi come SQL. APOC Procedures sono il meccanismo standard. Richiedono:
- `neo4j-apoc-core` nella configurazione plugins.
- `apoc.trigger.enabled=true` nella configurazione del database.
- Neo4j 5.x (alcune API APOC sono cambiate tra versioni).

### 5.7 Fragilità config.yml, madifica a id experiement, broke system
Using comments to expose to the user what part of file you can modify freely, and what part of the configuration is the scope of the lineage system!

### 5.8 Experimental Explosion
Riscrivere intera codebase ogni branch puo portare a problemi di storage e limiti di size, in versioni future, il base experiment avra il 100% del codice iniziale, e gli esperimenti derivati avranno solo le changes salvate sotto forma di diff, per ricostruire lo stato in un determinato momento, una funzionalità applicherà changes in modod sequenziale da base_experiement fino allo stato target.

### 6. UI del lineage system

**TO DEFINE**

---

## 7.  Update Documentation

Update with changes: 
- workflow.md
- README.md
- docs/*.md aggiungendo docs per nuovi moduli e iniettndo in quelli esistenti eventuali modifiche