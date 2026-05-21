# CLAUDE.md -- FineTuning-Lineage

## Project SCENARIO

### Architettura

Creazione di un modulo custom che funge da hook/decorator, che agisce da middleware di observability avanzato, che non si limita a loggare gli esperiementi, ma fa un update avanzato in base alle modifiche e ai risultati di ogni training execution.

Quindi:

1) Creazione di un modulo stile langfuse, che usa hook/decorator, EASY TO INTEGRATE.
2) Server dependent, questo suistema ha un container con neo4j volume che viene aggiornato. Servono metodi di comunicazione nel package, che supporta la cattura delle esecuzioni con conseguente comunicazione al container, questo implica anche la gestione delle comuniucazione di eventuali macchine da remoto.
3) UI interna all' ecosistema per interagire con DB sottostante, utile per interrogazioni e salvataggio di nuovi modelli/Recipes/components atomici, o new base_experiment creation, edit dei metadati e discovery dei nomi e id da passare alle repository di codice per essere mappate nel DB tramite config files. (ho possibilità, se conosco il model_name del modello che sto usando nella mia codebase, o il framework, posso passarlo in config.yml, cosi hook puo fare update di nodi esistenti, cosi come starting ckp o altre strategie di retry, ovviamente hook puo anche farlo in autiomatico) 

### MAIN LOGIC

1) Possibilità di metadatare una codebase come esperimento (BASE_EXPERIMENT) o autodetect se URI del progetto manca nel DB. Andando a leggere campi del config.yml, se dati mancanti, errore specifico triggered.
2) Ogni volta che viene eseguita una run di train, hook deve pre-eseguire dei controlli per decidere quale update al DB deve essere effettuata, si utilizzano diffManagers con logica di attuazione specifica.
3) Raccoglie anche i feedback dalla terminazione dell' esperimento (creazione di ckp, cattura di HW/metrics logs come URI dove sono scritti) utile anche per settare lo stato di esecuzione dell'esperimento!


### Standard codice

- Python 3.10+
- Pydantic v2 per tutti i data model
- Neo4j for tracking storage

### Project-Specific Guidelines

- TDD development
- Every imported package class or decorator can exists, not invent anything 
- Ask Questions about choices, especially when a tradeoff emerging
- Start from a object oriented style, from abstarction to implementations
- Ensure always the maximum modularity and extendability
- we have a .venv in the project to run tests and other commands
- You do not assume anithing, if some context is missing, ask for a deep explanation
- After every User story or stage, you have to test and update documentation of the project application, test the User story and checking for a refactoring
- Updating documentation requires to modify only the relevat documents between README.md, workflow.md and files in docs/*

### PROJECT References
 docs/*

# CLAUDE.md General Guidelines

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

