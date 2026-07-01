// ─────────────────────────────────────────────────────────────────────────
// CONSTRAINTS
// ─────────────────────────────────────────────────────────────────────────

CREATE CONSTRAINT unique_recipe_id IF NOT EXISTS FOR (r:Recipe) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT name IF NOT EXISTS FOR (r:Recipe) REQUIRE r.name IS UNIQUE;
CREATE CONSTRAINT unique_exp_id IF NOT EXISTS FOR (e:Experiment) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT unique_ckp_id IF NOT EXISTS FOR (c:Checkpoint) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT unique_model_name IF NOT EXISTS FOR (m:Model) REQUIRE m.model_name IS UNIQUE;
CREATE CONSTRAINT unique_model_name IF NOT EXISTS FOR (m:Model) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT composite_component IF NOT EXISTS FOR (co:Component) REQUIRE (co.technique_code, co.framework_code) IS UNIQUE;

// ─────────────────────────────────────────────────────────────────────────
// INDEXES
// ─────────────────────────────────────────────────────────────────────────


CREATE INDEX experiment_dead_end IF NOT EXISTS
FOR (e:Experiment) ON (e.dead_end);

CREATE INDEX experiment_conclusion_type IF NOT EXISTS
FOR (e:Experiment) ON (e.conclusion_type);

CREATE INDEX experiment_is_base IF NOT EXISTS
FOR (e:Experiment) ON (e.is_base);


