# config_file/ Module — Config Parsing & Validation

## Overview

Handles all configuration concerns: parsing YAML files (config.yml, .lineage/experiment.yml, .lineage/server.yml), validating fields, and writing back updated state (UUID injection).

**Location:** `graph_lineage/config_file/`

## Public API

```python
from graph_lineage.config_file.data_classes import (
    LineageConfig,         # Composite: training + experiment
    ExperimentConfig,      # .lineage/experiment.yml (hook-managed)
    TrainingConfig,        # config.yml (user-owned)
    ModelMergingConfig,    # model_merging section
    RecipeConfig,          # recipe section
    OutputConfig,          # output section
)

# Factory method
LineageConfig.from_files(config_path: str) -> LineageConfig
```

## Components

### 1. `data_classes/` — Pydantic Models

**Purpose:** Define strict validation schemas for all config sections.

#### `lineage_config.py`
```python
class LineageConfig(BaseModel):
    """Composite configuration: training + experiment."""
    experiment: ExperimentConfig
    training: TrainingConfig
    # ... other sections
    
    @classmethod
    def from_files(cls, config_path: str) -> LineageConfig:
        """Load from split-config: config.yml + .lineage/experiment.yml"""
```

#### `experiment_config.py`
```python
class ExperimentConfig(BaseModel):
    """Hook-managed configuration from .lineage/experiment.yml"""
    id: str | None = None           # Auto-generated on first run
    derived_from: str | None = None # Parent experiment UUID
    base_experiment: str | None = None
    expected_run_type: str = "auto"
    previous_experiment_id: str | None = None
    checkpoint_resume_from: str | None = None
    status: str = "pending"  # pending | running | completed | failed
```

#### `recipe_config.py`
```python
class RecipeConfig(BaseModel):
    """Recipe (dataset configuration) reference."""
    id: str = Field(..., description="UUID of recipe in DB")
    name: str = Field(..., min_length=1)
    scope: str | None = None  # sft, dpo, rl, etc.
    tasks: list[str] = Field(default_factory=list)
    entries: dict[str, RecipeEntry]  # dataset paths → metadata
```

#### `model_merging_config.py`
```python
class ModelMergingConfig(BaseModel):
    """Configuration for model/checkpoint merging."""
    enabled: bool = False
    strategy: str = "ties"  # ties | slerp | dare_ties
    base_model_id: str | None = None
    source_checkpoints: list[str] = Field(default_factory=list)
```

#### `output_config.py`
```python
class OutputConfig(BaseModel):
    """Output directory + metrics tracking."""
    output_dir: str = Field(...)
    metrics_uri: str | None = None
    checkpoint_prefix: str = "checkpoint"
```

### 2. Config Validation

**Validation Strategy:**
- **Strict mode**: All required fields checked at parse time
- **Pydantic v2 Field constraints**: `min_length`, `max_length`, `pattern`, `gt`, `ge`, etc.
- **Custom validators**: Cross-field validation (e.g., if `model_merging.enabled`, require `source_checkpoints`)

**Validation Points:**
1. YAML parse-time: Pydantic raises `ValidationError` if schema violated
2. PRE-execution: `LineageConfig.from_files()` may raise custom errors
3. Rule engine: `ModelIdMismatchError` if model_id changed

### 3. Split Config Architecture

**Problem:** How to keep lineage system state separate from user training config?

**Solution:** Two files, two classes, one factory:

```
User edits:
  config.yml (TrainingConfig)
    └─ model.model_name, hyperparameters, recipe.id, output_dir, etc.

System manages:
  .lineage/experiment.yml (ExperimentConfig)
    └─ id, derived_from, status, checkpoint_resume_from, etc.

Unified view:
  LineageConfig.from_files()
    └─ Loads both, composes into one object for use
```

**Key Advantage:** User never touches `.lineage/` (zero corruption risk). Config is versionable. Lineage state is trackable.

---

## Data Flow

```
User runs: train("config.yml", "cuda:0")
       │
       ▼
LineageConfig.from_files("config.yml")
       │
       ├─ Read config.yml
       │  → Parse as TrainingConfig (Pydantic)
       │  → Validate model, recipe, output fields
       │
       ├─ Read .lineage/experiment.yml
       │  → Parse as ExperimentConfig (Pydantic)
       │  → Validate id, status, etc.
       │
       ├─ Merge both → LineageConfig
       │
       ▼
Composed Config (ready for rule engine)
       │
       ├─ Pass to detect_run_type()
       ├─ Pass to create_experiment_node()
       └─ Pass to post-execution checkpoint creation
```

---

## Split Config Example

**config.yml** (User-owned):
```yaml
model:
  model_name: "llama-7b"
  hyperparameters:
    learning_rate: 0.0001

recipe:
  id: "uuid-of-recipe"
  name: "my_recipe"

output:
  output_dir: /nfs/checkpoints
  metrics_uri: /nfs/metrics
```

**.lineage/experiment.yml** (System-managed):
```yaml
id: "e-2026-05-27-001"       # Auto-generated on first run
derived_from: null           # Populated if BRANCH
base_experiment: null
status: "pending"
checkpoint_resume_from: null # Set if RESUME
previous_experiment_id: "e-2026-05-27-001"  # For RETRY detection
```

---

## Validation Rules

### Required Fields
- `model.model_name` (no spaces, must exist)
- `recipe.id` (valid UUID or reference)
- `output.output_dir` (writable path)

### Optional but Important
- `experiment.expected_run_type` ("auto" | "NEW" | "RETRY" | "BRANCH")
  - If mismatch with detected type → warning (not error)
- `experiment.checkpoint_resume_from` (path or UUID of checkpoint)
  - If set + exists → RESUME strategy
- `model_merging.enabled` (bool)
  - If true → MERGE strategy

### Blocking Errors
- `model.model_id` mismatch (exit code 7)
- Missing recipe by UUID (exit code 6)
- Config parse error (exit code 2)

---

## Integration

### In Rule Engine
```python
from graph_lineage.config_file.data_classes import LineageConfig

config = LineageConfig.from_files(config_path)

# Access composite config
model_name = config.training.model.model_name
exp_id = config.experiment.id
recipe_id = config.training.recipe.id
```

### In Server (Remote Mode)
```python
# Client sends config fields as JSON payload
POST /api/v1/pre
  config: {
    model: {model_name: "llama-7b", ...},
    recipe: {id: "...", ...},
    output: {...}
  }

# Server deserializes to TrainingConfig
training_config = TrainingConfig(**request.config)
```

### In Streamlit UI
```python
# Load config for display
config = LineageConfig.from_files(project_path + "/config.yml")

# Show model, recipe, output settings in sidebar
```

---

## Testing

**Location:** `tests/test_config_*.py`

**Coverage:**
- YAML parsing (valid + invalid files)
- Pydantic validation (required fields, constraints)
- Split config loading (both files present/missing)
- Error messages (clear feedback for validation failures)

**Example:**
```python
def test_experiment_config_id_auto_generated():
    config = ExperimentConfig(id=None, ...)
    # On first save, id should be UUID

def test_training_config_model_name_required():
    with pytest.raises(ValidationError):
        TrainingConfig(model={})  # Missing model_name

def test_lineage_config_from_files_split():
    config = LineageConfig.from_files("path/to/config.yml")
    # Should load from both config.yml and .lineage/experiment.yml
    assert config.experiment.id is not None
    assert config.training.model.model_name is not None
```

---

## Troubleshooting

### Q: "Config validation failed with ValidationError"
**A:** Check the error message—it lists which field failed. Common: `model_name` missing, `recipe.id` not a UUID, `output_dir` doesn't exist.

### Q: "How do I change a config field without breaking lineage?"
**A:** Edit `config.yml` freely (training fields). Never edit `.lineage/experiment.yml` manually—let the system manage it. If lineage state is wrong, delete `.lineage/experiment.yml` and rerun (creates fresh).

### Q: "Can I have multiple configs for different runs?"
**A:** Yes. Create separate project directories, each with its own `config.yml` + `.lineage/experiment.yml`. Or keep one `.lineage/` but rename `config.yml` when switching setups.

---

## See Also

- [lineage.md](lineage.md) — How config is used in rule engine
- [docs/CONFIG.md](../CONFIG.md) — User-facing config reference
- [README.md](../../README.md) — Quick start config example

