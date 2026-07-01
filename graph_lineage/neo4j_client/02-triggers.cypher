// ============================================================================
// Neo4j 5.x APOC Triggers — Automation Layer
// ============================================================================
// Idempotent: Safe to run multiple times (trigger install uses 'neo4j' namespace)
// Execution: After 01-schema.cypher, before 03-seeds.cypher
//
// Installs 4 APOC triggers:
//   1. created_at_trigger — Auto-set created_at on node creation
//   2. updated_at_trigger — Auto-set updated_at on node updates
//   3. orphan_checkpoint_validation — Prevent orphan checkpoints
//   4. auto_increment_chain_id — Auto-increment chain_id scoped by experiment name
// ============================================================================

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 1: Automatic created_at timestamp on node creation
// ─────────────────────────────────────────────────────────────────────────
// Installs a trigger in the 'neo4j' namespace.
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
// TRIGGER 3: CHAIN_ID autoincrement assigner by experiment name
// ─────────────────────────────────────────────────────────────────────────
// Scopes the chain_id sequence dynamically based on the Experiment "name".
// When a new :Experiment is created, it calculates max(chain_id) + 1 
// ONLY for the experiments sharing the same name.

CALL apoc.trigger.install('neo4j', 'auto_increment_chain_id',
  'UNWIND apoc.trigger.nodesByLabel($createdNodes, "Experiment") AS new_node
   
   // Trova gli altri esperimenti esistenti con lo stesso identico nome
   OPTIONAL MATCH (old_node:Experiment {name: new_node.name})
   WHERE id(old_node) <> id(new_node)
   
   // Calcola il max chain_id + 1 isolato per quel nome/esperimento
   WITH new_node, coalesce(max(old_node.chain_id), 0) + 1 AS nextChainId
   
   // Assegna il valore seriale generato
   SET new_node.chain_id = nextChainId',
  {phase: 'before'}) YIELD name
RETURN "Trigger auto_increment_chain_id installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// END OF TRIGGERS
// ─────────────────────────────────────────────────────────────────────────