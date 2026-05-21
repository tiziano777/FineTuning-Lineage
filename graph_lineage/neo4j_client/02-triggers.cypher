// ============================================================================
// Neo4j 5.x APOC Triggers — Automation Layer
// ============================================================================
// Idempotent: Safe to run multiple times (trigger install uses 'neo4j' namespace)
// Execution: After 01-schema.cypher, before 03-seeds.cypher
//
// Installs 3 APOC triggers:
//   1. created_at_trigger — Auto-set created_at on node creation
//   2. updated_at_trigger — Auto-set updated_at on node updates
//   3. orphan_checkpoint_validation — Prevent orphan checkpoints
// ============================================================================

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 1: Automatic created_at timestamp on node creation
// ─────────────────────────────────────────────────────────────────────────
// Installs a trigger in the 'neo4j' namespace (installed once per DB).
// On each node creation: sets created_at = datetime() if not already set.

CALL apoc.trigger.install('neo4j', 'created_at_trigger',
  'UNWIND apoc.trigger.nodesByLabel($createdNodes, null) AS node
   SET node.created_at = coalesce(node.created_at, datetime())',
  {phase: 'before'}) YIELD name
RETURN "Trigger created_at_trigger installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 2: Automatic updated_at timestamp on property updates
// ─────────────────────────────────────────────────────────────────────────
// On each node update: sets updated_at = datetime() (always update timestamp).

CALL apoc.trigger.install('neo4j', 'updated_at_trigger',
  'UNWIND apoc.trigger.nodesByLabel($changedNodes, null) AS node
   SET node.updated_at = datetime()',
  {phase: 'before'}) YIELD name
RETURN "Trigger updated_at_trigger installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 3: Orphan Checkpoint validation
// ─────────────────────────────────────────────────────────────────────────
// Prevents creating Checkpoint nodes that are "orphan" (not connected to anything).
// Exception: If is_merging=true, checkpoint is allowed to be orphan (used during merge operations).
//
// A checkpoint must have at least one incoming relationship from parent experiment:
//   - PRODUCED (normal checkpoint from experiment)
//   - Or: is_merging=true (checkpoint participating in merge)
//
// See: LINEAGE_SYSTEM_ARCHITECTURE.md §3.5 Checkpoint Orphan Validation

CALL apoc.trigger.install('neo4j', 'orphan_checkpoint_validation',
  'UNWIND apoc.trigger.nodesByLabel($createdNodes, "Checkpoint") AS ckp
   WHERE NOT (ckp)-[:PRODUCED]->()
     AND NOT (ckp)-[:DERIVED_FROM]->()
     AND NOT (ckp)-[:RETRY_OF]->()
     AND NOT (ckp)-[:MERGED_FROM]->()
     AND NOT ckp.is_merging = true
   CALL apoc.util.validate(false, "Checkpoint %s is orphan (no parent) and is_merging != true", [ckp.ckp_id])',
  {phase: 'after'}) YIELD name
RETURN "Trigger orphan_checkpoint_validation installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// END OF TRIGGERS
// ─────────────────────────────────────────────────────────────────────────
// Next: Run 03-seeds.cypher for initial seed data population
//
