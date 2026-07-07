// ============================================================================
// Neo4j 5.x APOC Triggers — Automation Layer (Fixed)
// ============================================================================

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 1: Automatic created_at timestamp on node creation
// ─────────────────────────────────────────────────────────────────────────
CALL apoc.trigger.install('neo4j', 'created_at_trigger',
  'UNWIND $createdNodes AS node
   SET node.created_at = coalesce(node.created_at, datetime())',
  {phase: 'before'}) YIELD name
RETURN "Trigger created_at_trigger installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 2: Automatic updated_at timestamp on property updates
// ─────────────────────────────────────────────────────────────────────────
// Note: $changedNodes provides a map of {node, properties}. We extract the node.
CALL apoc.trigger.install('neo4j', 'updated_at_trigger',
  'UNWIND keys($assignedNodeProperties) AS key
   // Skip if the only thing changing is the updated_at timestamp itself
   WITH key WHERE key <> "updated_at"
   
   UNWIND $assignedNodeProperties[key] AS prop
   WITH prop.node AS node
   SET node.updated_at = datetime()',
  {phase: 'before'}) YIELD name
RETURN "Trigger updated_at_trigger installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 3: AUTOINCREMENT chain_id
// ─────────────────────────────────────────────────────────────────────────
CALL apoc.trigger.install('neo4j', 'auto_increment_chain_id',
  'UNWIND $createdNodes AS new_node
   WITH new_node
   WHERE "Experiment" IN labels(new_node)
   
   // Find other experiments with the same name
   OPTIONAL MATCH (old_node:Experiment {name: new_node.name})
   WHERE id(old_node) <> id(new_node)
   
   // Calculate max chain_id + 1 for that name/experiment
   WITH new_node, coalesce(max(old_node.chain_id), 0) + 1 AS nextChainId
   
   // Assign the generated serial value
   SET new_node.chain_id = nextChainId',
  {phase: 'before'})
YIELD name
RETURN "Trigger auto_increment_chain_id installed" AS message;

// ─────────────────────────────────────────────────────────────────────────
// TRIGGER 4: Calculate 'deep' value on Node Creation (with its relationship)
// ─────────────────────────────────────────────────────────────────────────
CALL apoc.trigger.install('neo4j', 'calculate_deep_trigger',
  'UNWIND $createdNodes AS new_node
   WITH new_node 
   WHERE "Experiment" IN labels(new_node)
   
   // Cerchiamo se il nuovo nodo è stato collegato a un padre nella stessa transazione
   OPTIONAL MATCH (new_node)-[r]->(parent_node:Experiment)
   WHERE type(r) IN ["RESUMED_FROM", "DERIVED_FROM", "RETRY_FROM"]
   
   // Se c\'è un padre, calcola la profondità, altrimenti assegna 0 (nodo radice)
   WITH new_node, coalesce(parent_node.deep, 0) AS parentDeep, count(parent_node) AS hasParent
   
   SET new_node.deep = CASE WHEN hasParent > 0 THEN parentDeep + 1 ELSE 0 END',
  {phase: 'before'}
) YIELD name
RETURN "Trigger calculate_deep_trigger installed" AS message;