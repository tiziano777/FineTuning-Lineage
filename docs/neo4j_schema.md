# Neo4j Lineage Schema

## Overview

FineTuning-Lineage uses Neo4j 5.x as the lineage graph store. The schema includes 5 node types, 7 relation types, 5 UNIQUE constraints, 3 BTREE indexes, and 3 APOC triggers for automatic timestamp management.

## Node Types

| Node Type | Fields | Purpose | Example |
|-----------|--------|---------|---------|
| **:Recipe** | `recipe_id` (UNIQUE), `name`, `version` | Technique definition | `recipe_id: "lora_trl_7b"` |
| **:Model** | `model_name` (UNIQUE), `model_id`, `type` | Base model metadata | `model_name: "llama-7b-instruct"` |
| **:Experiment** | `exp_id` (UNIQUE), `config_hash`, `code_hash`, `req_hash`, `status`, `created_at`, `updated_at` | Training run instance | `exp_id: "e-20260410-001"`, `status: "completed"` |
| **:Checkpoint** | `id` (UNIQUE), `name`, `derived_from`, `epoch`, `run`, `uri`, `metrics` (JSON), `is_merging`, `is_usable`, `created_at`, `updated_at` | Saved artifact + metadata | `id: "uuid"`, `name: "checkpoint-500"`, `metrics: {"loss": 0.23}` |
| **:Component** | `(technique_code, framework_code)` (UNIQUE composite), `name` | Technique+framework pair | `technique_code: "dpo"`, `framework_code: "trl"` |

## Relation Types

| Relation | From | To | Purpose | Example |
|----------|------|----|-|---------|---------|
| **PRODUCED** | :Experiment | :Checkpoint | Experiment produced checkpoint | `exp1 -[:PRODUCED]-> ckp5` |
| **DERIVED_FROM** | :Experiment | :Experiment | Config/code change (branch) | `exp2 -[:DERIVED_FROM]-> exp1` |
| **RETRY_FROM** | :Experiment | :Experiment | Same config, different seed | `exp3 -[:RETRY_FROM]-> exp1` |
| **MERGED_FROM** | :Checkpoint | :Checkpoint | Merge multiple checkpoints | `ckp_merged -[:MERGED_FROM]-> [ckp1, ckp2]` |
| **USES_TECHNIQUE** | :Experiment | :Component | Technique used | `exp1 -[:USES_TECHNIQUE]-> (dpo_trl)` |
| **USES_MODEL** | :Experiment | :Model | Base model | `exp1 -[:USES_MODEL]-> (llama-7b)` |
| **USES_RECIPE** | :Experiment | :Recipe | Recipe used | `exp1 -[:USES_RECIPE]-> (lora_recipe)` |

## Constraints & Indexes

### UNIQUE Constraints (5)

```cypher
CREATE CONSTRAINT unique_recipe_id FOR (r:Recipe) REQUIRE r.recipe_id IS UNIQUE;
CREATE CONSTRAINT unique_exp_id FOR (e:Experiment) REQUIRE e.exp_id IS UNIQUE;
CREATE CONSTRAINT unique_ckp_id FOR (c:Checkpoint) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT unique_model_name FOR (m:Model) REQUIRE m.model_name IS UNIQUE;
CREATE CONSTRAINT composite_component FOR (co:Component) REQUIRE (co.technique_code, co.framework_code) IS UNIQUE;
```

### BTREE Indexes (3)

```cypher
CREATE INDEX idx_exp_config_hash FOR (e:Experiment) ON (e.config_hash);
CREATE INDEX idx_exp_code_hash FOR (e:Experiment) ON (e.code_hash);
CREATE INDEX idx_exp_req_hash FOR (e:Experiment) ON (e.req_hash);
```

## APOC Triggers (3 types)

**Timestamp Trigger 1:** Auto-set `created_at` on node creation
```cypher
CREATE TRIGGER timestamp_created_at
ON CREATE OF (n:Experiment|Checkpoint)
SET n.created_at = datetime()
```

**Timestamp Trigger 2:** Auto-set `updated_at` on property change
```cypher
CREATE TRIGGER timestamp_updated_at
ON SET n:Experiment|Checkpoint
SET n.updated_at = datetime()
```

**Orphan Checkpoint Validation:** Reject Checkpoint with no parent (unless `is_merging=true`)
```cypher
CREATE TRIGGER orphan_validation
ON SET (c:Checkpoint)
WHERE NOT EXISTS((c)<-[:PRODUCED]-()) AND c.is_merging = false
RAISE ERROR "Checkpoint must have PRODUCED relation from Experiment"
```

## Common Queries

**Get all experiments for a model:**
```cypher
MATCH (e:Experiment)-[:USES_MODEL]->(m:Model {model_name: "llama-7b"})
RETURN e.exp_id, e.config_hash, e.status ORDER BY e.created_at DESC;
```

**Get checkpoint lineage (full history):**
```cypher
MATCH path = (ckp:Checkpoint)-[:PRODUCED_BY*0..]-(e:Experiment)
RETURN path;
```

**Find branches from an experiment:**
```cypher
MATCH (source:Experiment {exp_id: "e-001"})<-[:DERIVED_FROM]-(target:Experiment)
RETURN target.exp_id, target.config_hash;
```

**Check for circular dependencies (should be 0):**
```cypher
MATCH path = (e:Experiment)-[:DERIVED_FROM|RETRY_FROM*]->(e)
RETURN COUNT(path) AS circular_count;
```

**Get all checkpoints from a merged experiment:**
```cypher
MATCH (ckp:Checkpoint)-[:MERGED_FROM*]->(src:Checkpoint)
RETURN ckp.id, ckp.name, COLLECT(src.id) AS sources;
```

## Performance Notes

- **BTREE indexes on hash fields**: Fast handshake queries (~10ms for find_experiment_by_hashes)
- **UNIQUE constraints**: Prevent duplicates; no data cleanup needed
- **APOC triggers**: Run server-side; no round-trip latency
- **Composite key on Component**: (technique_code, framework_code) uniquely identifies a training approach

## Schema Design Rationale

**Why separate :Component nodes?**
- Allows tracking which framework implements which technique
- Enables analysis: "Which frameworks support GRPO?" (query all components linked to GRPO recipe)

**Why separate :Recipe, :Model, :Component?**
- Enables reuse across experiments
- Reduces redundant storage
- Allows aggregation queries


