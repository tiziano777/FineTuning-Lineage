# SkyPilot Experiment Orchestrator

Orchestratore per lanciare esperimenti DPO su cloud con [SkyPilot](https://docs.skypilot.co), supportando N varianti di configurazione in parallelo.

---

## Struttura

```
/dpo-setup/modules/skypilot/
├── schedules/
│   └── base_schedule.sh        # Script principale — legge config, genera task, lancia
├── tasks/
│   └── task_template.yaml      # Template SkyPilot (risorse, setup, run)
├── variants/
│   ├── lr_high_beta_strong.yml # Esempio: override learning rate e beta
│   └── lora_small.yml          # Esempio: override parametri LoRA
└── generated/                  # Output generato (gitignored)
    ├── config_*.yml            # Config mergiate per ogni variante
    └── task_*.yaml             # Task YAML pronti per sky launch
```

---

## Componenti

### `schedules/base_schedule.sh`

Il cuore dell'orchestratore. Responsabilita:

1. **Legge le risorse hardware** da `config.yml` (sezione `hardware.skypilot.resources`) tramite `yq`
2. **Mergia le varianti** — per ogni file in `variants/`, esegue un deep-merge sul config base producendo un config completo
3. **Genera i task SkyPilot** — sostituisce le variabili nel template con `envsubst`
4. **Lancia i cluster** — chiama `sky launch` per ogni variante

Dipendenze: `yq` (v4+), `envsubst` (GNU gettext), `sky` CLI.

### `tasks/task_template.yaml`

Template del task SkyPilot. Contiene placeholder (`${VAR}`) che vengono risolti dallo script:

| Variabile | Sorgente | Descrizione |
|-----------|----------|-------------|
| `${SKY_ACCELERATORS}` | `hardware.skypilot.resources.accelerators` | GPU tipo e quantita (es. `A100-80GB:1`) |
| `${SKY_CPUS}` | `hardware.skypilot.resources.cpus` | CPU minime richieste |
| `${SKY_MEMORY}` | `hardware.skypilot.resources.memory` | RAM minima richiesta |
| `${CONFIG_PATH}` | path generato | Path al config mergiato per questa variante |
| `${EXPERIMENT_NAME}` | `experiment.name` + `experiment.id` | Nome cluster e identificativo |

### `variants/`

File YAML minimali che contengono **solo i parametri da sovrascrivere**. Tutto il resto viene ereditato dal `config.yml` base.

Esempio — cambiare learning rate:
```yaml
experiment:
  id: ex2-dpo-lora-0.4-lr5e5
model:
  training:
    learning_rate: 5e-05
```

Regole:
- La struttura deve rispecchiare quella del `config.yml` (stesse chiavi, stesso nesting)
- Puoi sovrascrivere qualsiasi sezione: `model.training`, `model.peft`, `experiment`, ecc.
- Un file = una variante = un cluster SkyPilot

### `generated/`

Directory di output (gitignored). Contiene:
- `config_<nome_variante>.yml` — config completo dopo il merge
- `task_<indice>.yaml` — task YAML pronto per SkyPilot

Utile per debug: puoi ispezionare i file generati prima di lanciare senza `--dry-run`.

---

## Workflow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ config.yml  │────>│              │────>│ generated/       │
│ (base)      │     │ base_schedule│     │  config_v1.yml   │
└─────────────┘     │    .sh       │     │  config_v2.yml   │
                    │              │     │  task_0.yaml     │
┌─────────────┐     │   yq merge   │     │  task_1.yaml     │
│ variants/   │────>│   envsubst   │     └────────┬────────┘
│  v1.yml     │     │              │              │
│  v2.yml     │     └──────────────┘              │
└─────────────┘                                   v
                                          ┌───────────────┐
                                          │  sky launch   │
                                          │  (per ognuno) │
                                          └───────────────┘
```

**Passo per passo:**

1. Lo script legge `hardware.skypilot.resources` dal config base
2. Per ogni variante, crea una copia del config base e ci sovrascrive i parametri della variante (deep merge con `yq`)
3. Genera un file task YAML sostituendo i placeholder nel template
4. Lancia `sky launch -c <cluster_name> <task.yaml>` per ogni variante
5. Sul cluster remoto, SkyPilot esegue `python train.py <config_path>` — `train.py` gia accetta il config path come primo parametro.

---

## Uso

```bash
cd modules/accelerators/orchetrator/skypilot

# Dry-run: mostra cosa verrebbe lanciato senza eseguire
bash schedules/base_schedule.sh --dry-run

# Lancio singolo (config base, nessuna variante)
bash schedules/base_schedule.sh

# Lancio con varianti sequenziali
bash schedules/base_schedule.sh variants/lr_high_beta_strong.yml variants/lora_small.yml

# Lancio parallelo di tutte le varianti
bash schedules/base_schedule.sh --parallel variants/*.yml

# Config base custom
bash schedules/base_schedule.sh --config /path/to/altro_config.yml variants/*.yml

# Prefisso cluster custom
bash schedules/base_schedule.sh --cluster-prefix mio-exp variants/*.yml
```

---

## Creare una nuova variante

1. Crea un file in `variants/`:
   ```bash
   touch variants/mia_variante.yml
   ```

2. Aggiungi solo le chiavi da cambiare (stessa struttura del config.yml):
   ```yaml
   experiment:
     name: mio-esperimento-v1
   model:
     training:
       learning_rate: 1e-04
       num_train_epochs: 5
   ```

3. Testa con dry-run:
   ```bash
   bash schedules/base_schedule.sh --dry-run variants/mia_variante.yml
   ```

4. Ispeziona il config generato:
   ```bash
   cat generated/config_mia_variante.yml
   ```

5. Lancia:
   ```bash
   bash schedules/base_schedule.sh variants/mia_variante.yml
   ```

---

## Requisiti

| Tool | Versione | Installazione |
|------|----------|---------------|
| `yq` | v4+ | `brew install yq` / `pip install yq` |
| `envsubst` | qualsiasi | `brew install gettext` (incluso in GNU/Linux) |
| `sky` | latest | `pip install skypilot` |

---

## Integrazione Lineage Tracker

L'orchestratore inietta automaticamente `experiment.base_experiment_id` nel config mergiato di ogni variante, permettendo al lineage tracker di creare una topologia a stella (tutte le varianti derivano dallo stesso base experiment).

### Prerequisiti

- Il **base experiment** deve essere stato eseguito almeno una volta tramite il tracker (`@envelope.tracker()`), cosi che il suo UUID venga scritto in `config.yml` nel campo `experiment.id`.

### Cosa fa l'orchestratore

Dopo il merge (`yq`) di base + variant, lo script:
1. Legge `experiment.id` dal config base (che contiene l'UUID assegnato dal tracker)
2. Lo inietta come `experiment.base_experiment_id` nel config mergiato della variante

Il tracker, leggendo il config mergiato, risolve il parent per ID (non per URI), garantendo che tutte le varianti puntino allo stesso base — anche in esecuzione parallela.

### Constraints per i file `variants/*.yml`

**DEVE contenere:**
```yaml
experiment:
  id: <nome-unico-variante>   # Identificativo human-readable (sovrascritto da UUID dal tracker)
```

**NON DEVE contenere:**
- `experiment.base_experiment_id` — iniettato automaticamente dall'orchestratore
- `experiment.previous_experiment_id` — deve restare null/vuoto

**PUO' contenere:**
- Qualsiasi override su `model.*`, `recipe.*`, `hardware.*`, `output.*`

### Risultato nel grafo

```
[BASE: UUID-A]
    |-- DERIVED_FROM --> [VARIANT: lr-5e5-beta03]  (diff: learning_rate, beta)
    |-- DERIVED_FROM --> [VARIANT: lora-small]      (diff: r, alpha, dropout)
    |-- DERIVED_FROM --> [VARIANT: warmup-500]      (diff: warmup_steps)
```

---

## Note

- **train.py** accetta il config path come primo argomento (`sys.argv[1]`), quindi ogni variante viene eseguita col suo config dedicato senza modifiche al codice di training
- I cluster vengono nominati `<experiment_name>-variant-<indice>` — usa `sky status` per monitorarli
- Per fermare un esperimento: `sky down <cluster_name>`
- Per vedere i log: `sky logs <cluster_name>`
