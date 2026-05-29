# data_classes/ Module — Neo4j Entity Models

## Overview

Defines Pydantic v2 models for all Neo4j node types: Experiment, Checkpoint, Recipe, Model, Component. Ensures type safety and validation across the system.

**Location:** `graph_lineage/data_classes/neo4j/`

## Public API

```python
from graph_lineage.data_classes.neo4j.nodes import (
    Experiment,
    Checkpoint,
    Recipe,
    Model,
    Component,
)
```

## Node Types

### Experiment
```python
class Experiment(BaseModel):
    id: str | None = None
    description: Optional[str] = Field("", description="Experiment description")
    uri: str = Field("", description="Path scaffold on worker")
    base: bool = Field(True, description="True for base experiment, False for derived")

    status: Optional[str] = Field("RUNNING", description="RUNNING | COMPLETED | FAILED | PAUSED")
    exit_status: Optional[str] = None
    exit_msg: Optional[str] = None
    strategy: str = Field("", description="NEW | RESUME | BRANCH | RETRY")

    model_uri: str = Field("", description="model_uri used for this run")
    model_id: str = Field("", description="model_id used for entire lineage experimentations")

    codebase: dict = Field(default_factory=dict, description="base=True: full snapshot dict[str, str]; base=False: unified diff dict")
    changed_files: list[str] = Field(default_factory=list, description="List of filenames that changed (for non-base experiments)")

    usable: bool = Field(True, description="Is experiment usable")
    manual_save: bool = Field(False, description="Manually saved")

    metrics_uri: str = Field("", description="Pointer to unified training + HW metrics")
    
    created_at: datetime
    updated_at: datetime

```

### Checkpoint
```python
class Checkpoint(BaseModel):
    id: str  # UNIQUE
    name: str
    derived_from: str = Field("", description="Associated Model")
    epoch: int
    run: int
    metrics: dict  # JSON: {loss: 0.23, accuracy: 0.95}
    uri: str | None  # Path to checkpoint on disk (null if deleted)
    created_at: datetime
    updated_at: datetime
    is_merging: bool = False  # If true, skip orphan validation
```

### Recipe
```python
class Recipe(BaseModel):
    id: str | None = None
    name: str = Field(None, min_length=1, description="Recipe name (must be unique)")
    description: Optional[str] = Field(None, description="Recipe description")
    scope: Optional[str] = Field(None, description="Scope for this recipe (e.g., 'sft', 'preference', 'rl')")
    tasks: list[str] = Field(default_factory=list, description="Tasks associated with this recipe")
    tags: list[str] = Field(default_factory=list, description="Tags for categorizing recipes")
    derived_from: Optional[str] = Field(None, description="Optional UUID of parent recipe this was derived from")
    entries: dict[str, RecipeEntry]  # Dataset paths → metadata
    created_at: datetime
    updated_at: datetime
```

### Model
```python
class Model(BaseModel):
    model_name: str = Field(..., min_length=1, description="Unique model name")
    version: Optional[str] = Field("", description="Model version")
    uri: str = Field("", description="Path or URI to model")
    url: Optional[str] = Field("", description="Model URL (HuggingFace, etc)")
    doc_url: Optional[str] = Field("", description="Documentation URL")
    description: Optional[str] = Field("", description="Model description")
    kind: Optional[str] = Field("", description="Model kind: BASE | ADAPTER | MERGED")
    architecture_info_ref: Optional[str] = Field("", description="Reference to architecture document")
  
```

### Component
```python
class Component(BaseModel):
    name: str = Field(..., min_length=1, description="Component name = setup template folder name (e.g. dpo_trl)")
    uri: Optional[str] = Field("", description="Internal URI to setup template: ./graph_lineage/setups/{name}")

    description: Optional[str] = Field("", description="Component description")

    technique_code: str = Field(..., min_length=1, description="Technique code (e.g., grpo, sft)")
    framework_code: str = Field(..., min_length=1, description="Framework code (e.g., unsloth, trl)")
    opt_code: Optional[str] = Field("", description="Optimization code, Lora, Qlora, etc")

    docs_url: Optional[str] = Field("", description="Documentation URL")

```

---

## Design Rationale

**Why separate nodes for Recipe, Model, Component?**
- **Reusability**: Same recipe used across many experiments
- **Aggregation queries**: "Which models are used most?" (scan Model nodes, not Experiment edges)
- **Flexibility**: Add new properties without reshaping Experiment

---

## Integration

### In lineage/neo4j_ops.py
```python
from graph_lineage.data_classes.neo4j.nodes import Experiment, Checkpoint

exp = Experiment(
    exp_id=new_id,
    config_hash=hash1,
    code_hash=hash2,
    req_hash=hash3,
    status="running"
)
await client.create_experiment(exp)
```

### In streamlit_ui/db/repository/
```python
from graph_lineage.data_classes.neo4j.nodes import Recipe

recipe = Recipe(recipe_id=uuid, name="r1", entries={...})
await recipe_repo.upsert(recipe)
```

---

## See Also

- [neo4j_schema.md](../neo4j_schema.md) — Cypher schema definitions
- [neo4j_client.md](neo4j_client.md) — How these are persisted

