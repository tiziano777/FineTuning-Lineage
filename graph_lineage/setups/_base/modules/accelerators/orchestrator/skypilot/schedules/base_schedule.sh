#!/usr/bin/env bash
# =============================================================================
# base_schedule.sh — SkyPilot Experiment Orchestrator (Sequenziale/Coda)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(dirname "$SCRIPT_DIR")"
# Risale fino alla root del tuo repository
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Defaults definiti dalla documentazione
BASE_CONFIG="${REPO_ROOT}/config.yml"
LINEAGE_FILE="${REPO_ROOT}/.lineage/experiment.yml"
TEMPLATE_FILE="${MODULE_DIR}/tasks/task_template.yaml"
GENERATED_DIR="${MODULE_DIR}/generated"
CLUSTER_NAME="azure-gpu-cluster"
DRY_RUN=false
PARALLEL=false 
CLUSTER_PREFIX=""
VARIANT_FILES=()

# -----------------------------------------------------------------------------
# 🛠️ AUTOMATIC INFRASTRUCTURE SETUP (Check & Link della cartella .sky nella Home)
# -----------------------------------------------------------------------------
HOME_SKY_DIR="${HOME}/.sky"
REPO_SKY_SRC="${MODULE_DIR}/.sky/ssh_node_pools.yaml"

if [ "$DRY_RUN" = false ]; then
  # Se il file di configurazione non esiste nella Home dell'utente
  if [ ! -f "${HOME_SKY_DIR}/ssh_node_pools.yaml" ]; then
    echo "⚠️ Configurazione SkyPilot non trovata in ${HOME_SKY_DIR}"
    
    # Controlla se esiste il file sorgente nel repository
    if [ -f "$REPO_SKY_SRC" ]; then
      echo "📦 Inizializzazione automatica dell'infrastruttura dal repository..."
      mkdir -p "$HOME_SKY_DIR"
      
      # Crea un link simbolico (scelta consigliata: le modifiche nel repo si riflettono nella home)
      ln -sf "$REPO_SKY_SRC" "${HOME_SKY_DIR}/ssh_node_pools.yaml"
      echo "✅ Collegamento simbolico creato con successo: ${HOME_SKY_DIR}/ssh_node_pools.yaml -> $REPO_SKY_SRC"
      
      # Inizializza il pool SSH su SkyPilot automaticamente
      echo "🚀 Esecuzione automatica di 'sky ssh up'..."
      sky ssh up
    else
      echo "❌ ERROR: File di configurazione sorgente non trovato in $REPO_SKY_SRC" >&2
      echo "Assicurati di aver creato il file di configurazione nel tuo modulo." >&2
      exit 1
    fi
  fi
fi

# Parsing degli argomenti (Allineato al 100% alla documentazione)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) BASE_CONFIG="$2"; shift 2 ;;
    --lineage) LINEAGE_FILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --parallel) PARALLEL=true; shift ;; 
    --cluster-prefix) CLUSTER_PREFIX="$2"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    -h|--help) 
      echo "SkyPilot Experiment Orchestrator"
      echo "Usage: $0 [--config PATH] [--lineage PATH] [--dry-run] [--cluster-prefix PREFIX] [variants/..]"
      exit 0 ;;
    *) VARIANT_FILES+=("$1"); shift ;;
  esac
done

# Check preliminare dell'ambiente Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 è richiesto per l'unione dei file di configurazione." >&2
  exit 1
fi

mkdir -p "$GENERATED_DIR"

if [[ ${#VARIANT_FILES[@]} -eq 0 ]]; then
  VARIANT_FILES=("__base__")
fi

# -----------------------------------------------------------------------------
# Motore Python per estrazione sicura e Deep Merge (Sostituisce yq ed envsubst)
# -----------------------------------------------------------------------------
py_extract_field() {
  python3 -c "
import yaml
with open('$1') as f:
    d = yaml.safe_load(f) or {}
for k in '$2'.split('.'):
    d = d.get(k, '') if isinstance(d, dict) else ''
print(str(d).replace('+', ''))
" 2>/dev/null || echo "$3"
}

py_deep_merge_and_lineage() {
  local out="$1" l_file="$2" b_file="$3" v_file="$4"
  python3 -c "
import yaml

def deep_merge(dict1, dict2):
    for key, value in dict2.items():
        if isinstance(value, dict) and key in dict1 and isinstance(dict1[key], dict):
            deep_merge(dict1[key], value)
        else:
            dict1[key] = value

# 1. Leggi UUID dal lineage file del Base Experiment
with open('$l_file') as f:
    lin = yaml.safe_load(f) or {}
base_uuid = lin.get('experiment', {}).get('id', 'null')

# 2. Carica il Base Config del progetto
with open('$b_file') as f:
    base_config = yaml.safe_load(f) or {}

# 3. Se presente una variante, caricala
variant_config = {}
if '$v_file':
    with open('$v_file') as f:
        variant_config = yaml.safe_load(f) or {}

# Costruisci il dizionario finale applicando le regole di Lineage Tracker
final_dict = {}
deep_merge(final_dict, base_config)
deep_merge(final_dict, variant_config)

# Iniezione automatica dei metadati per la topologia a stella (Richiesta da Doc)
if 'experiment' not in final_dict:
    final_dict['experiment'] = {}

final_dict['experiment']['base_experiment_id'] = base_uuid
final_dict['experiment']['previous_experiment_id'] = None

with open('$out', 'w') as f:
    yaml.dump(final_dict, f, default_flow_style=False)
"
}

# Estrazione Risorse Hardware per SkyPilot (Rimuovendo i caratteri '+' non graditi)
SKY_ACCELERATORS=$(py_extract_field "$BASE_CONFIG" "hardware.skypilot.resources.accelerators" "A100-80GB:1")
SKY_CPUS=$(py_extract_field "$BASE_CONFIG" "hardware.skypilot.resources.cpus" "128")
SKY_MEMORY=$(py_extract_field "$BASE_CONFIG" "hardware.skypilot.resources.memory" "216")

# -----------------------------------------------------------------------------
# Ciclo di generazione ed esecuzione delle Varianti
# -----------------------------------------------------------------------------
for i in "${!VARIANT_FILES[@]}"; do
  variant_file="${VARIANT_FILES[$i]}"
  run_id=$(date +%Y%m%d_%H%M%S)"_${i}"
  
  # Creazione di una sandbox isolata dentro 'generated' per evitare race conditions
  run_sandbox_dir="${GENERATED_DIR}/run_${run_id}"
  mkdir -p "$run_sandbox_dir"
  
  variant_name="base"
  if [[ "$variant_file" == "__base__" ]]; then
    variant_file=""
    echo "=== Preparazione Variante: BASE ==="
  else
    variant_name=$(basename "$variant_file" .yml)
    echo "=== Preparazione Variante: ${variant_name} ==="
  fi

  merged_config_path="${run_sandbox_dir}/config_${variant_name}.yml"
  
  # Esegui il Deep Merge e l'iniezione del Lineage Tracker
  py_deep_merge_and_lineage "$merged_config_path" "$LINEAGE_FILE" "$BASE_CONFIG" "$variant_file"

  # Estrai il nome finale dell'esperimento per battezzare il job SkyPilot
  experiment_name=$(py_extract_field "$merged_config_path" "experiment.name" "dpo_exp")
  experiment_id=$(py_extract_field "$merged_config_path" "experiment.id" "no_id")

  # Calcola il nome del task/job
  job_display_name="${experiment_name}"
  if [[ -n "$CLUSTER_PREFIX" ]]; then
    job_display_name="${CLUSTER_PREFIX}_${variant_name}"
  fi

  # Genera il file task compilando il template (Sostituisce envsubst)
  task_yaml="${run_sandbox_dir}/task_${variant_name}.yaml"
  
  # Ottieni il percorso relativo della configurazione rispetto alla REPO_ROOT 
  # in modo che SkyPilot possa risolverlo dopo aver sincronizzato la workdir
  relative_config_path="modules/skypilot/generated/run_${run_id}/config_${variant_name}.yml"

  python3 -c "
with open('$TEMPLATE_FILE') as f:
    content = f.read()

content = content.replace('__TASK_NAME__', '${job_display_name}')
content = content.replace('__SKY_ACCELERATORS__', '${SKY_ACCELERATORS}')
content = content.replace('__SKY_CPUS__', '${SKY_CPUS}')
content = content.replace('__SKY_MEMORY__', '${SKY_MEMORY}')
content = content.replace('__REPO_ROOT__', '${REPO_ROOT}')
content = content.replace('__RELATIVE_CONFIG_PATH__', '${relative_config_path}')

with open('$task_yaml', 'w') as f:
    f.write(content)
"

  # Sottomissione alla coda o Dry Run
  if [[ "$DRY_RUN" == true ]]; then
    echo "   [DRY-RUN] sky launch -c $CLUSTER_NAME $task_yaml --detach"
    echo "   [DRY-RUN] Configurazione fusa generata in: $merged_config_path"
    echo ""
  else
    echo "   Sottomissione in coda su cluster '$CLUSTER_NAME'..."
    sky launch -c "$CLUSTER_NAME" "$task_yaml" -y --detach
    echo "   Job sottomesso con successo."
    echo ""
  fi
done

echo "=== Elaborazione completata. Directory di Staging: $GENERATED_DIR ==="
if [[ "$DRY_RUN" == false ]]; then
  echo "Controlla lo stato della coda hardware con il comando: sky queue"
fi