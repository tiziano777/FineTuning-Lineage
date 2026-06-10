#!/usr/bin/env bash
# =============================================================================
# base_schedule.sh — SkyPilot Experiment Orchestrator
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKYPILOT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

# Defaults
BASE_CONFIG="${REPO_ROOT}/config.yml"
LINEAGE_FILE="${REPO_ROOT}/.lineage/experiment.yml"
DRY_RUN=false
PARALLEL=false
CLUSTER_PREFIX=""
VARIANT_FILES=()

# -----------------------------------------------------------------------------
# Arg parsing
# -----------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      BASE_CONFIG="$2"; shift 2 ;;
    --lineage)
      LINEAGE_FILE="$2"; shift 2 ;;
    --dry-run)
      DRY_RUN=true; shift ;;
    --parallel)
      PARALLEL=true; shift ;;
    --cluster-prefix)
      CLUSTER_PREFIX="$2"; shift 2 ;;
    -h|--help)
      head -30 "$0" | tail -25; exit 0 ;;
    *)
      VARIANT_FILES+=("$1"); shift ;;
  esac
done

# -----------------------------------------------------------------------------
# Helper: Sanitize for cluster name only
# -----------------------------------------------------------------------------
sanitize_for_cluster() {
  local input="$1"
  echo "$input" | sed 's/"//g' | sed 's/[^a-zA-Z0-9._-]/_/g' | sed 's/__*/_/g' | sed 's/^_//;s/_$//'
}

# -----------------------------------------------------------------------------
# Dependency checks
# -----------------------------------------------------------------------------
for cmd in envsubst sky; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' is required but not found in PATH." >&2
    exit 1
  fi
done

# Detect yq type
if ! command -v yq &>/dev/null; then
  echo "ERROR: 'yq' is required but not found in PATH." >&2
  exit 1
fi

if yq --version 2>&1 | grep -q "mikefarah"; then
  YQ_TYPE="go"
else
  YQ_TYPE="python"
fi

if [[ ! -f "$BASE_CONFIG" ]]; then
  echo "ERROR: Base config not found: $BASE_CONFIG" >&2
  exit 1
fi

if [[ ! -f "$LINEAGE_FILE" ]]; then
  echo "ERROR: Lineage file not found: $LINEAGE_FILE" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# Read lineage metadata using raw string extraction
# -----------------------------------------------------------------------------
LINEAGE_EXP_ID=$(grep -E '^[[:space:]]+id:' "$LINEAGE_FILE" | head -1 | sed 's/.*id:[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
LINEAGE_NAME=$(grep -E '^[[:space:]]+name:' "$LINEAGE_FILE" | head -1 | sed 's/.*name:[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
LINEAGE_BASE_EXP_ID=$(grep -E '^[[:space:]]+base_experiment_id:' "$LINEAGE_FILE" | head -1 | sed 's/.*base_experiment_id:[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
LINEAGE_PREVIOUS_ID=$(grep -E '^[[:space:]]+previous_experiment_id:' "$LINEAGE_FILE" | head -1 | sed 's/.*previous_experiment_id:[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
LINEAGE_IS_BASE=$(grep -E '^[[:space:]]+base:' "$LINEAGE_FILE" | head -1 | sed 's/.*base:[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//' | tr '[:upper:]' '[:lower:]')

[[ "$LINEAGE_PREVIOUS_ID" == "null" ]] && LINEAGE_PREVIOUS_ID=""
[[ "$LINEAGE_BASE_EXP_ID" == "null" ]] && LINEAGE_BASE_EXP_ID=""

if [[ -z "$LINEAGE_EXP_ID" ]] || [[ "$LINEAGE_EXP_ID" == "null" ]]; then
  echo "ERROR: Invalid lineage file - missing experiment.id" >&2
  exit 1
fi

if [[ -z "$LINEAGE_IS_BASE" ]]; then
  LINEAGE_IS_BASE="false"
fi

echo "=== Lineage Metadata (from $LINEAGE_FILE) ==="
echo "  experiment.id: $LINEAGE_EXP_ID"
echo "  experiment.name: $LINEAGE_NAME"
echo "  experiment.base: $LINEAGE_IS_BASE"
echo "  experiment.base_experiment_id: $LINEAGE_BASE_EXP_ID"
echo "  experiment.previous_experiment_id: $LINEAGE_PREVIOUS_ID"
echo ""

# -----------------------------------------------------------------------------
# Read SkyPilot resources - KEEP ORIGINAL FORMAT
# -----------------------------------------------------------------------------
SKY_ACCELERATORS=$(yq '.hardware.skypilot.resources.accelerators' "$BASE_CONFIG" | sed 's/"//g')
SKY_CPUS=$(yq '.hardware.skypilot.resources.cpus' "$BASE_CONFIG" | sed 's/"//g')
SKY_MEMORY=$(yq '.hardware.skypilot.resources.memory' "$BASE_CONFIG" | sed 's/"//g')

echo "=== SkyPilot Resources (from $BASE_CONFIG) ==="
echo "  accelerators: $SKY_ACCELERATORS"
echo "  cpus:         $SKY_CPUS"
echo "  memory:       $SKY_MEMORY"
echo ""

# -----------------------------------------------------------------------------
# Prepare generated output directory
# -----------------------------------------------------------------------------
GENERATED_DIR="${SKYPILOT_DIR}/generated"
mkdir -p "$GENERATED_DIR"

# -----------------------------------------------------------------------------
# Create a YAML fragment with lineage metadata
# -----------------------------------------------------------------------------
create_lineage_fragment() {
  local output="$1"
  local is_base="$2"
  
  cat > "$output" << EOF
experiment:
  id: ${LINEAGE_EXP_ID}
  name: ${LINEAGE_NAME}
  base: ${is_base}
  base_experiment_id: ${LINEAGE_BASE_EXP_ID:-null}
  previous_experiment_id: ${LINEAGE_PREVIOUS_ID:-null}
EOF
}

# -----------------------------------------------------------------------------
# Build complete config with lineage metadata
# -----------------------------------------------------------------------------
build_config_with_lineage() {
  local output="$1"
  local variant_override="${2:-}"
  local is_base="${3:-false}"
  
  local base_with_lineage="${output}.base.tmp"
  local lineage_fragment="${output}.lineage.tmp"
  
  create_lineage_fragment "$lineage_fragment" "$is_base"
  
  if [[ "$YQ_TYPE" == "go" ]]; then
    yq eval-all '
      select(fileIndex == 0) as $lineage |
      select(fileIndex == 1) as $config |
      $lineage * $config
    ' "$lineage_fragment" "$BASE_CONFIG" > "$base_with_lineage"
  else
    yq -s '.[0] * .[1]' "$lineage_fragment" "$BASE_CONFIG" > "$base_with_lineage" 2>/dev/null
  fi
  
  if [[ -n "$variant_override" && -f "$variant_override" ]]; then
    if [[ "$YQ_TYPE" == "go" ]]; then
      yq eval-all '
        select(fileIndex == 0) as $base |
        select(fileIndex == 1) as $variant |
        $base * $variant
      ' "$base_with_lineage" "$variant_override" > "$output"
    else
      yq -s '.[0] * .[1]' "$base_with_lineage" "$variant_override" > "$output" 2>/dev/null
    fi
    rm -f "$base_with_lineage"
  else
    mv "$base_with_lineage" "$output"
  fi
  
  rm -f "$lineage_fragment"
}

# -----------------------------------------------------------------------------
# If no variants provided, run with base config directly
# -----------------------------------------------------------------------------
if [[ ${#VARIANT_FILES[@]} -eq 0 ]]; then
  VARIANT_FILES=("__base__")
fi

# -----------------------------------------------------------------------------
# Launch function
# -----------------------------------------------------------------------------
launch_variant() {
  local variant_file="$1"
  local variant_index="$2"
  local variant_config

  if [[ "$variant_file" == "__base__" ]]; then
    variant_config="${GENERATED_DIR}/config_base.yml"
    build_config_with_lineage "$variant_config" "" "true"
    echo "--- Variant: BASE (no overrides) ---"
  else
    if [[ ! -f "$variant_file" ]]; then
      echo "WARNING: Variant file not found: $variant_file — skipping" >&2
      return 1
    fi
    local variant_name
    variant_name=$(basename "$variant_file" .yml)
    variant_config="${GENERATED_DIR}/config_${variant_name}.yml"
    
    build_config_with_lineage "$variant_config" "$variant_file" "false"
    
    echo "--- Variant: $variant_name ---"
    echo "    overrides: $variant_file"
  fi

  # Read back experiment metadata
  local experiment_name
  experiment_name=$(yq '.experiment.name' "$variant_config" 2>/dev/null | sed 's/"//g' || echo "unknown")
  local experiment_id
  experiment_id=$(yq '.experiment.id' "$variant_config" 2>/dev/null | sed 's/"//g' || echo "unknown")
  local is_base
  is_base=$(yq '.experiment.base // false' "$variant_config" 2>/dev/null | sed 's/"//g' || echo "false")

  # Create safe cluster name
  local safe_cluster_base=$(sanitize_for_cluster "$experiment_name")
  
  local cluster_name
  if [[ -n "$CLUSTER_PREFIX" ]]; then
    cluster_name="${CLUSTER_PREFIX}-${variant_index}"
  else
    cluster_name="${safe_cluster_base}-${variant_index}"
    cluster_name="${cluster_name:0:64}"
    cluster_name=$(echo "$cluster_name" | sed 's/-$//')
  fi

  echo "    experiment.name: $experiment_name"
  echo "    experiment.id: $experiment_id"
  echo "    experiment.base: $is_base"
  echo "    config:  $variant_config"
  echo "    cluster: $cluster_name"
  echo ""

  # Generate task YAML
  local task_yaml="${GENERATED_DIR}/task_${variant_index}.yaml"
  
  cat > "$task_yaml" << EOF
# SkyPilot Task Template - Generated by base_schedule.sh
name: ${experiment_name}-${experiment_id}

resources:
  accelerators: ${SKY_ACCELERATORS}
  cpus: ${SKY_CPUS}
  memory: ${SKY_MEMORY}
  disk_size: 200

workdir: ${REPO_ROOT}

envs:
  CONFIG_PATH: ${variant_config}
  EXPERIMENT_NAME: ${experiment_name}_${experiment_id}
  PYTHONUNBUFFERED: 1

setup: |
  echo "Setting up environment..."
  cd ${REPO_ROOT}
  if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
  fi

run: |
  echo "Starting training with config: \${CONFIG_PATH}"
  cd ${REPO_ROOT}
  python train.py --config \${CONFIG_PATH}
EOF

  echo "YAML to run: $task_yaml"
  
  # Launch
  if [[ "$DRY_RUN" == true ]]; then
    echo "    [DRY-RUN] sky launch -c $cluster_name $task_yaml"
    echo ""
    echo "=== Generated Task YAML Content ==="
    cat "$task_yaml"
    echo ""
  else
    sky launch -c "$cluster_name" "$task_yaml" -y
  fi
}

# -----------------------------------------------------------------------------
# Execute all variants
# -----------------------------------------------------------------------------
for i in "${!VARIANT_FILES[@]}"; do
  launch_variant "${VARIANT_FILES[$i]}" "$i"
done

echo "=== Done. Generated files in: $GENERATED_DIR ==="