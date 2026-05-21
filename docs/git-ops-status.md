Ora ho il quadro completo. Ecco l'analisi capabilities per ogni punto:

Analisi Capabilities — History Management & Branching
1) Visualizzare stato intermedio t_k (t_0 < k < n)
Status: PRESENTE (parziale)

reconstruct_codebase(chain) fa esattamente questo — prende la catena [base, diff1, ..., diffK] e applica i diff sequenzialmente. Quello che manca è la query Cypher per estrarre la catena dal grafo:

-- Serve una funzione tipo: get_chain(base_id, target_id) -> list[Experiment]
MATCH path = (target:Experiment {exp_id: $target_id})-[:DERIVED_FROM*]->(base:Experiment {base: true})
RETURN nodes(path) ORDER BY length(path) DESC

Effort per completare: BASSO — serve solo la query Cypher + una funzione wrapper reconstruct_at(target_exp_id) che: query chain → ordina t_0...t_k → chiama reconstruct_codebase().

2) Rollback a k con eliminazione k+1...n
Status: ASSENTE — FATTIBILE ma con vincoli

Operazione distruttiva. Richiede:

Query: MATCH (e:Experiment)-[:DERIVED_FROM*]->(k:Experiment {exp_id: $k_id}) per trovare tutti successori
DELETE di tutti nodi/relazioni successori + checkpoints associati
Aggiornare l'esperimento k come "ultimo" della catena
Rischio: ALTO in contesto ad albero (vedi punto 5). Se k ha branch paralleli, eliminare da k+1 in poi distrugge anche i branch alternativi.

Proposta di mitigazione: flag force: bool + dry-run che mostra quanti nodi/branch verrebbero eliminati prima di procedere. E soft-delete con usable: false invece di DELETE fisico.

3) Compattazione diff (squash tra x e y)
Status: ASSENTE — FATTIBILE

Concettualmente semplice con le primitives che abbiamo:

reconstruct_codebase([base...x]) → snapshot_x
reconstruct_codebase([base...y]) → snapshot_y
compute_snapshot_diff(snapshot_x, snapshot_y) → diff_compatto
DELETE nodi intermedi x+1...y-1
Aggiorna y.codebase = diff_compatto, y.DERIVED_FROM → x
Rischio: MEDIO — perdi la granularità intermedia. Se un esperimento intermedio ha checkpoint o metadati utili, vanno preservati o migrati.

Vincolo: come per (2), funziona solo su catene lineari. Con branch, i nodi intermedi potrebbero avere fork.

4-5-6) Evoluzione ad albero (branch paralleli)
Status: IL GRAFO LO SUPPORTA GIÀ — ma le funzioni Python no.

Lo schema Neo4j supporta nativamente l'albero: nulla vieta che più esperimenti abbiano DERIVED_FROM verso lo stesso parent. La struttura è un DAG (directed acyclic graph).

          t_0 (base)
          ├── t_1 (lr=1e-4)
          │   ├── t_2 (lr=1e-4, batch=32)
          │   └── t_3 (lr=1e-4, batch=64)  ← branch parallelo
          └── t_4 (lr=1e-3)                ← altro branch dal base

Cosa manca a livello Python:

Capability	Stato	Effort
Navigare branch (figli di un nodo)	Query Cypher triviale, no Python wrapper	BASSO
Ricostruire un branch specifico	reconstruct_codebase funziona già — serve solo la catena corretta dal grafo	BASSO
Switching tra branch (check out t_3 → t_4)	Ricostruisci entrambi indipendentemente — non serve "undo"	BASSO
Fork da qualsiasi nodo	Nuovo exp con DERIVED_FROM → nodo_scelto — già possibile nello schema	GIÀ POSSIBILE
Protezione branch da rollback distruttivo (punto 5)	Manca — serve check pre-delete: "ha figli?"	BASSO
Capabilities AGGIUNTIVE che non hai menzionato
Ho identificato queste user stories potenziali:

A) Merge di branch (convergenza)
Due branch paralleli (t_2, t_4) possono essere uniti creando un nuovo esperimento che ha DERIVED_FROM verso entrambi. Lo schema lo supporta (relazione multipla). Il diff del merge sarebbe calcolato come 3-way merge rispetto all'antenato comune.

Effort: ALTO — 3-way merge è complesso. Ma il modello dati lo supporta.

B) Pruning selettivo (soft-delete branch)
Invece di eliminare, marcare un sotto-albero come usable: false. I dati restano nel grafo per lineage storico, ma la UI li nasconde/graya-out. Utilissimo per il tuo caso d'uso: "testa N varianti, poi nascondi quelle scarse".

Effort: BASSO — usable: bool esiste già nel modello Experiment!

C) Diff tra branch (confronto laterale)
Dato t_2 e t_4 (branch diversi), calcolare il diff tra loro per capire cosa cambia tra due varianti. Richiede: ricostruisci entrambi → diff tra i risultati.

Effort: BASSO — tutte le primitive esistono, serve solo la funzione wrapper.

D) Common ancestor (LCA - Lowest Common Ancestor)
Per merge e branch diff serve trovare l'antenato comune. Neo4j lo supporta con:

MATCH path1 = (a:Experiment {exp_id: $id1})-[:DERIVED_FROM*]->(ancestor)
MATCH path2 = (b:Experiment {exp_id: $id2})-[:DERIVED_FROM*]->(ancestor)
RETURN ancestor ORDER BY length(path1) + length(path2) ASC LIMIT 1

Effort: BASSO

E) Tagging / Snapshots nominati
Dare un nome a uno stato specifico ("best_lr_experiment", "pre_quantization") per ritrovarlo senza ricordare l'exp_id.

Effort: BASSO — basta usare Experiment.description o aggiungere un campo tags: list[str].

F) Chain depth analytics
Report su profondità catena, numero branches, fan-out per nodo. Utile per capire quando fare squash o pruning.

Effort: BASSO — pure Cypher queries.

Riepilogo
#	Capability	Stato	Effort	Rischio
1	Visualizzare stato intermedio	PARZIALE — manca query Cypher	Basso	Nessuno
2	Rollback distruttivo	ASSENTE	Medio	Alto (branch)
3	Squash/compattazione	ASSENTE	Medio	Medio (perdita granularità)
4	Evoluzione ad albero	SUPPORTATA dal grafo, mancano wrapper	Basso	Nessuno
5	Protezione fork da rollback	ASSENTE	Basso	Nessuno
6	Branch paralleli + pruning	QUASI PRONTO (usable: bool esiste)	Basso	Nessuno
A	Merge di branch	ASSENTE	Alto	Medio (3-way merge)
B	Soft-delete / pruning selettivo	QUASI PRONTO	Basso	Nessuno
C	Diff tra branch diversi	PRIMITIVES PRONTE	Basso	Nessuno
D	Common ancestor (LCA)	ASSENTE — Cypher semplice	Basso	Nessuno
E	Tagging / named snapshots	ASSENTE	Basso	Nessuno
F	Chain analytics	ASSENTE — pure Cypher	Basso	Nessuno
Raccomandazione
Per le fasi future, proporrei di raggruppare queste capabilities in 2 user stories:

"History Navigation" (effort basso, alto valore): punti 1, 4, B, C, D, E, F — tutte read-only o soft operations
"History Mutation" (effort medio, rischio alto): punti 2, 3, A — operazioni distruttive, servono protezioni e dry-run
Vuoi che aggiunga queste come fasi future nel roadmap, o le parcheggiamo nel backlog?