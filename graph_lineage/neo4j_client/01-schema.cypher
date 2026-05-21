// ============================================================================
// Neo4j 5.x Complete Schema Definition — Lineage System
// ============================================================================
// Idempotent: Safe to run multiple times (all CREATE use IF NOT EXISTS)
// Maps directly to Pydantic models in envelope/middleware/shared/nodes.py
//
// Execution order:
//   1. This file (01-schema.cypher) — node types, relationships, constraints, indexes
//   2. 02-triggers.cypher — APOC triggers for automation
//   3. 03-seeds.cypher — initial seed data
// ============================================================================

// ─────────────────────────────────────────────────────────────────────────
// NODE TYPE DEFINITIONS
// ─────────────────────────────────────────────────────────────────────────

// Note: Neo4j does not require explicit node type definitions (labels are applied on creation).
// These are logical documentation of the schema structure.
// See properties and constraints below.

// ─────────────────────────────────────────────────────────────────────────
// UNIQUE CONSTRAINTS (5 total)
// ─────────────────────────────────────────────────────────────────────────

// Recipe: unique recipe_id (primary key from Pydantic RecipeNode.recipe_id)
CREATE CONSTRAINT unique_recipe_id IF NOT EXISTS
  FOR (r:Recipe) REQUIRE r.recipe_id IS UNIQUE;

// Recipe: unique name (for user-facing identification)
CREATE CONSTRAINT unique_recipe_name IF NOT EXISTS
  FOR (r:Recipe) REQUIRE r.name IS UNIQUE;

// Experiment: unique exp_id (primary key from Pydantic ExperimentNode.exp_id)
CREATE CONSTRAINT unique_experiment_id IF NOT EXISTS
  FOR (e:Experiment) REQUIRE e.exp_id IS UNIQUE;

// Checkpoint: unique ckp_id (primary key from Pydantic CheckpointNode.ckp_id)
CREATE CONSTRAINT unique_checkpoint_id IF NOT EXISTS
  FOR (c:Checkpoint) REQUIRE c.ckp_id IS UNIQUE;

// Model: unique model_name (primary key from Pydantic ModelNode.model_name)
CREATE CONSTRAINT unique_model_name IF NOT EXISTS
  FOR (m:Model) REQUIRE m.model_name IS UNIQUE;

// Component: composite unique key (technique_code, framework_code)
// Ensures no duplicate (technique, framework) pairs in capability matrix
CREATE CONSTRAINT unique_component_composite IF NOT EXISTS
  FOR (co:Component) REQUIRE (co.technique_code, co.framework_code) IS UNIQUE;

// ─────────────────────────────────────────────────────────────────────────
// BTREE INDEXES (3 on Experiment hashes)
// ─────────────────────────────────────────────────────────────────────────
// These speed up handshake queries: find_experiment_by_hashes(config_hash, code_hash, req_hash)
// See: Phase 2 Database Layer, handshake protocol in LINEAGE_SYSTEM_ARCHITECTURE.md

CREATE INDEX idx_experiment_config_hash IF NOT EXISTS
  FOR (e:Experiment) ON (e.config_hash);

CREATE INDEX idx_experiment_code_hash IF NOT EXISTS
  FOR (e:Experiment) ON (e.code_hash);

CREATE INDEX idx_experiment_req_hash IF NOT EXISTS
  FOR (e:Experiment) ON (e.req_hash);

// ─────────────────────────────────────────────────────────────────────────
// RELATIONSHIP TYPE DOCUMENTATION
// ─────────────────────────────────────────────────────────────────────────
// Neo4j stores relationships as explicit typed edges.
// These are created at runtime when experiments/checkpoints are recorded.
// Documented here for schema reference.
//
// 8 Relationship Types (from LINEAGE_SYSTEM_ARCHITECTURE.md §3.2):
//
//  1. USED_FOR        (Component) -[r]-> (Experiment)
//     Stack tecnologico usato: which technique+framework pair was used for this experiment
//
//  2. SELECTED_FOR    (Model) -[r]-> (Experiment)
//     Modello base selezionato: which base model was used for this experiment
//
//  3. BASED_ON        (Experiment) -[r]-> (Recipe)
//     Configurazione di input: which recipe/dataset configuration sourced this experiment
//
//  4. PRODUCED        (Experiment) -[r]-> (Checkpoint)
//     Checkpoint generato: which experiment produced this checkpoint (atomic)
//
//  5. DERIVED_FROM    (Experiment) -[r: {diff_patch: JSON}]-> (Experiment)
//     Branching logico: config/code changed (BRANCH strategy)
//     Properties: diff_patch (git-style diffs of changed files)
//
//  6. STARTED_FROM    (Experiment) -[r]-> (Checkpoint)
//     Branching fisico (optional): which checkpoint was used as weights baseline for BRANCH
//
//  7. RETRY_OF        (Experiment) -[r]-> (Experiment)
//     Stesso setup, nuovo tentativo: same config, different seed (RETRY strategy)
//
//  8. MERGED_FROM     (Checkpoint) -[r]-> (Checkpoint)
//     Merge N-a-1 di pesi: new checkpoint created by merging source checkpoints

// ─────────────────────────────────────────────────────────────────────────
// NODE PROPERTY SCHEMAS
// ─────────────────────────────────────────────────────────────────────────
// Documented mapping between Pydantic models and Neo4j node properties:

//
// Recipe Node
// Pydantic: envelope/middleware/shared/nodes.py :: RecipeNode
//
//   recipe_id: str            → Property: recipe_id (UNIQUE, PK)
//   name: str                 → Property: name (UNIQUE, user-facing)
//   description: str          → Property: description (defaults "")
//   scope: str                → Property: scope (defaults "")
//   tasks: list[str]          → Property: tasks (list/array in Neo4j)
//   tags: list[str]           → Property: tags (list/array for metadata)
//   issued: datetime          → Property: issued
//   modified: datetime        → Property: modified
//   derived_from: str|None    → Property: derived_from (optional, recursive ref to recipe_id)
//   config_yaml: str          → Property: config_yaml (frozen YAML content snapshot)
//   entries: list[dict]       → Property: entries (list of dicts: dataset metadata)
//   created_at: datetime|None → Property: created_at (set by APOC trigger)
//   updated_at: datetime|None → Property: updated_at (set by APOC trigger)
//

//
// Model Node
// Pydantic: envelope/middleware/shared/nodes.py :: ModelNode
//
//   model_name: str           → Property: model_name (UNIQUE, PK)
//   version: str              → Property: version (e.g., "main", defaults "")
//   uri: str                  → Property: uri (local path or remote, defaults "")
//   url: str                  → Property: url (HuggingFace/hub URL, defaults "")
//   doc_url: str              → Property: doc_url (documentation URL, defaults "")
//   architecture_info_ref: str → Property: architecture_info_ref (defaults "")
//   description: str          → Property: description (defaults "")
//   created_at: datetime|None → Property: created_at (set by APOC trigger)
//   updated_at: datetime|None → Property: updated_at (set by APOC trigger)
//

//
// Experiment Node
// Pydantic: envelope/middleware/shared/nodes.py :: ExperimentNode
//
//   exp_id: str               → Property: exp_id (UNIQUE, PK)
//   model_id: str             → Property: model_id (foreign key, defaults "")
//   status: str               → Property: status (RUNNING|COMPLETED|FAILED|PAUSED, default "RUNNING")
//   exit_status: str|None     → Property: exit_status (exit code, optional)
//   exit_msg: str|None        → Property: exit_msg (error message, optional)
//   strategy: str             → Property: strategy (NEW|RESUME|BRANCH|RETRY, default "")
//
//   config_hash: str          → Property: config_hash (SHA256 of config.yaml, for handshake)
//   code_hash: str            → Property: code_hash (SHA256 of train.py+rewards/*, for handshake)
//   req_hash: str             → Property: req_hash (SHA256 of requirements.txt, for handshake)
//   [3 BTREE indexes on these hashes for fast find_experiment_by_hashes() queries]
//
//   config: str               → Property: config (complete config.yaml text snapshot, frozen)
//   train: str                → Property: train (complete train.py text snapshot, frozen)
//   rewards: list[str]        → Property: rewards (list of reward file contents, parallel to rewards_filenames)
//   rewards_filenames: list[str] → Property: rewards_filenames (names of reward files)
//   requirements: str         → Property: requirements (complete requirements.txt text)
//
//   scaffold_local_uri: str   → Property: scaffold_local_uri (path on worker machine, defaults "")
//   scaffold_remote_uri: str  → Property: scaffold_remote_uri (path on master/storage, defaults "")
//
//   usable: bool              → Property: usable (experiment is valid, defaults true)
//   manual_save: bool         → Property: manual_save (manually saved, defaults false)
//   metrics_uri: str          → Property: metrics_uri (pointer to training metrics, defaults "")
//   hw_metrics_uri: str       → Property: hw_metrics_uri (pointer to hardware metrics, defaults "")
//   description: str          → Property: description (defaults "")
//
//   created_at: datetime|None → Property: created_at (set by APOC trigger on creation)
//   updated_at: datetime|None → Property: updated_at (set by APOC trigger on modification)
//

//
// Checkpoint Node
// Pydantic: envelope/middleware/shared/nodes.py :: CheckpointNode
//
//   ckp_id: str               → Property: ckp_id (UNIQUE, PK)
//   epoch: int                → Property: epoch (training epoch number, ≥0)
//   run: int                  → Property: run (run index within epoch, ≥0)
//   metrics_snapshot: dict    → Property: metrics_snapshot (JSON snapshot of metrics at save time)
//   uri: str|None             → Property: uri (file://, s3://, nfs://, or NULL if discarded)
//   is_usable: bool           → Property: is_usable (can be used for resume, defaults true)
//   is_merging: bool          → Property: is_merging (partecipates in merge operation, defaults false)
//   description: str          → Property: description (defaults "")
//
//   created_at: datetime|None → Property: created_at (set by APOC trigger)
//   updated_at: datetime|None → Property: updated_at (set by APOC trigger)
//
// Note: Orphan checkpoint validation (APOC trigger) requires PRODUCED or is_merging=true
//

//
// Component Node
// Pydantic: envelope/middleware/shared/nodes.py :: ComponentNode
//
//   technique_code: str       → Property: technique_code (e.g., "grpo", "sft", "dpo")
//   framework_code: str       → Property: framework_code (e.g., "trl", "unsloth", "axolotl")
//   [Composite UNIQUE constraint on (technique_code, framework_code)]
//
//   docs_url: str             → Property: docs_url (documentation link, defaults "")
//   description: str          → Property: description (defaults "")
//
//   created_at: datetime|None → Property: created_at (set by APOC trigger)
//   updated_at: datetime|None → Property: updated_at (set by APOC trigger)
//

// ─────────────────────────────────────────────────────────────────────────
// END OF SCHEMA DEFINITION
// ─────────────────────────────────────────────────────────────────────────
// Next: Run 02-triggers.cypher for APOC automation
// Then:  Run 03-seeds.cypher for initial seed data population
