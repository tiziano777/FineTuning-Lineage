#!/usr/bin/env bash
# =============================================================================
# base_schedule.sh — SkyPilot Experiment Orchestrator
#
# Reads hardware.skypilot config from config.yml, supports N experiment variants
# via separate YAML override files merged onto the base config.
#
# Usage:
#   bash base_schedule.sh [OPTIONS] [variant1.yml variant2.yml ...]
#
# Options:
#   --config <path>    Base config file (default: config.yml in repo root)
#   --dry-run          Show commands without executing
#   --parallel         Launch all variants in parallel (default: sequential)
#   --cluster-prefix   Custom cluster name prefix (default: experiment name)
#
# Examples:
#   bash base_schedule.sh --dry-run
#   bash base_schedule.sh variants/lr_high.yml variants/lr_low.yml
#   bash base_schedule.sh --parallel --config /path/to/config.yml variants/*.yml
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKYPILOT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

# Defaults
BASE_CONFIG="${REPO_ROOT}/config.yml"
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
    --dry-run)
      DRY_RUN=true; shift ;;
    --parallel)
      PARALLEL=true; shift ;;
    --cluster-prefix)
      CLUSTER_PREFIX="$2"; shift 2 ;;
    -h|--help)
      head -25 "$0" | tail -20; exit 0 ;;
    *)
      VARIANT_FILES+=("$1"); shift ;;
  esac
done

# -----------------------------------------------------------------------------
# Dependency checks
# -----------------------------------------------------------------------------
for cmd in yq envsubst sky; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' is required but not found in PATH." >&2
    exit 1
  fi
done

if [[ ! -f "$BASE_CONFIG" ]]; then
  echo "ERROR: Base config not found: $BASE_CONFIG" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# Read SkyPilot resources from base config
# -----------------------------------------------------------------------------
SKY_ACCELERATORS=$(yq '.hardware.skypilot.resources.accelerators' "$BASE_CONFIG")
SKY_CPUS=$(yq '.hardware.skypilot.resources.cpus' "$BASE_CONFIG")
SKY_MEMORY=$(yq '.hardware.skypilot.resources.memory' "$BASE_CONFIG")

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

TASK_TEMPLATE="${SKYPILOT_DIR}/tasks/task_template.yaml"
if [[ ! -f "$TASK_TEMPLATE" ]]; then
  echo "ERROR: Task template not found: $TASK_TEMPLATE" >&2
  exit 1
fi

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
    # No overrides — use base config as-is
    variant_config="${GENERATED_DIR}/config_base.yml"
    cp "$BASE_CONFIG" "$variant_config"
    echo "--- Variant: base (no overrides) ---"
  else
    if [[ ! -f "$variant_file" ]]; then
      echo "WARNING: Variant file not found: $variant_file — skipping" >&2
      return 1
    fi
    local variant_name
    variant_name=$(basename "$variant_file" .yml)
    variant_config="${GENERATED_DIR}/config_${variant_name}.yml"

    # Deep merge: base config * variant overrides
    yq eval-all 'select(fileIndex == 0) * select(fileIndex == 1)' \
      "$BASE_CONFIG" "$variant_file" > "$variant_config"

    # Inject lineage tracking: base_experiment_id from base config
    local base_exp_uuid
    base_exp_uuid=$(yq '.experiment.id' "$BASE_CONFIG")
    if [[ -z "$base_exp_uuid" || "$base_exp_uuid" == "null" ]]; then
      echo "ERROR: Base config experiment.id is empty. Run base experiment first to get UUID." >&2
      return 1
    fi
    yq -i ".experiment.base_experiment_id = \"$base_exp_uuid\"" "$variant_config"

    echo "--- Variant: $variant_name ---"
    echo "    overrides: $variant_file"
  fi

  # Read experiment name from the (possibly overridden) variant config
  local experiment_name
  experiment_name=$(yq '.experiment.name' "$variant_config")
  local experiment_id
  experiment_id=$(yq '.experiment.id' "$variant_config")

  # Export vars for envsubst
  export SKY_ACCELERATORS SKY_CPUS SKY_MEMORY
  export CONFIG_PATH="$variant_config"
  export EXPERIMENT_NAME="${experiment_name}_${experiment_id}"

  # Generate task YAML
  local task_yaml="${GENERATED_DIR}/task_${variant_index}.yaml"
  envsubst < "$TASK_TEMPLATE" > "$task_yaml"

  # Determine cluster name
  local cluster_name
  if [[ -n "$CLUSTER_PREFIX" ]]; then
    cluster_name="${CLUSTER_PREFIX}-${variant_index}"
  else
    cluster_name="${experiment_name}-variant-${variant_index}"
  fi

  echo "    config:  $variant_config"
  echo "    task:    $task_yaml"
  echo "    cluster: $cluster_name"
  echo ""

  # Launch
  if [[ "$DRY_RUN" == true ]]; then
    echo "    [DRY-RUN] sky launch -c $cluster_name $task_yaml"
    echo ""
  else
    sky launch -c "$cluster_name" "$task_yaml" -y
  fi
}

# -----------------------------------------------------------------------------
# Execute all variants
# -----------------------------------------------------------------------------
PIDS=()
for i in "${!VARIANT_FILES[@]}"; do
  if [[ "$PARALLEL" == true && "$DRY_RUN" == false ]]; then
    launch_variant "${VARIANT_FILES[$i]}" "$i" &
    PIDS+=($!)
  else
    launch_variant "${VARIANT_FILES[$i]}" "$i"
  fi
done

# Wait for parallel jobs
if [[ "$PARALLEL" == true && "$DRY_RUN" == false && ${#PIDS[@]} -gt 0 ]]; then
  echo "=== Waiting for ${#PIDS[@]} parallel launches... ==="
  for pid in "${PIDS[@]}"; do
    wait "$pid" || echo "WARNING: Launch PID $pid failed"
  done
fi

echo "=== Done. Generated files in: $GENERATED_DIR ==="
