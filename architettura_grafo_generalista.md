# Architettura a Grafo Generalista con Wrapper Verticali

## Adaptive case management:

- **Case** (l'istanza operativa: pratica, cliente, task, fascicolo — qualunque "cosa" un umano stia portando avanti)

- **Actor** (chi agisce: umano, ruolo, o l'LLM stesso come attore tracciato)

- **Event/Stage** (qualunque cosa accada nel tempo dentro il case, senza un ordine fisso a priori — questo è il punto chiave di ACM contro BPMN: non serve definire in anticipo la sequenza)

- **Artifact** (puntatore al risultato, mai il contenuto pesante)

- **Source** (riferimento a cosa ha informato una decisione: norma, dataset, documento esterno)

- **Supersession** come relazione trasversale, per qualunque dominio in cui "la versione nuova non cancella la vecchia ma la scavalca"

# ACM Esteso: Ontologia dei Nodi Core
Per supportare la complessità di multi-utenza, tracciamento di codebase, esperimenti e task quotidiane, il tuo meta-grafo in Neo4j deve poggiare su questi sei pilastri strutturali:

1. Case (Il Contenitore Dinamico)Definizione: Il nodo radice dell'unità di lavoro (un esperimento di AI, una codebase da refactorizzare, una pratica di un cliente). Non ha uno stato sequenziale fisso, ma definisce l'obiettivo di business e il perimetro di accesso.Estensione Agentica: Funge da "contesto primario". Quando l'LLM viene attivato su un caso, il sistema recupera questo nodo e la sua stella di primo livello per mappare lo spazio delle opzioni disponibili.

2. Actor (L'Agente di Azione)Definizione: L'entità che compie le azioni. Può essere un essere umano, un ruolo del team (es. "Lead Data Scientist"), o un agente LLM specifico con le sue direttive di sistema (es. "Agent_Code_Optimizer").Estensione Agentica: Permette la tracciabilità delle responsabilità e la gestione della concorrenza. Se un LLM agisce per conto di un utente, il grafo registra (Actor:LLM)-[:ACTS_ON_BEHALF_OF]->(Actor:Human).

3. Event/Stage (Il Battito Temporale)Definizione: Qualsiasi accadimento o macro-fase che si materializza nel ciclo di vita del caso. Non ha una sequenza rigida, ma registra pietre miliari (es. "Checkpoint_10k_Raggiunto", "Feedback_Cliente_Ricevuto").Estensione Agentica: Serve come catalizzatore per i trigger. L'evento non è un passaggio bloccante, ma una notifica semantica nel grafo che gli altri agenti o sistemi possono ascoltare per reagire.

4. Artifact (Il Puntatore di Stato)Definizione: Il risultato tangibile di un'azione. È sempre e solo un puntatore leggero (un URI a un bucket S3, un path sul filesystem locale, un ID di riga in PostgreSQL, un hash di un commit Git).Estensione Agentica: Protegge la memoria del grafo. L'LLM non legge mai l'artefatto pesante direttamente dal grafo, ma ne vede la metadatazione (es. dimensione, tipo, metriche di score) per decidere se richiederne il download/lettura tramite un tool esterno.

5. Source (La Giustificazione Decisionale)Definizione: L'origine dell'informazione o del vincolo che ha guidato una scelta. Può essere un paper scientifico, una direttiva aziendale (es. nodo-regola GDPR), o un dataset di input.Estensione Agentica: Garantisce la tracciabilità e riduce le allucinazioni. Se l'LLM prende una decisione autonoma all'interno del caso, deve connettere il proprio Task di output alla Source utilizzata tramite una relazione [:BASED_ON].

6. Supersession (La Linea Temporale Dinamica)Definizione: La relazione trasversale [:SUPERSEDES] applicabile a qualsiasi dominio (codice, documenti, run, regole). La versione $N+1$ non cancella fisicamente la versione $N$, ma la scavalca logicamente.Estensione Agentica: Consente all'LLM di ricostruire la cronologia delle decisioni. Quando l'agente interroga il grafo, ignora per default i nodi superati (velocizzando la ricerca), ma può "scendere nella tana del bianconiglio" seguendo la catena di supersessione se deve capire perché una determinata scelta è stata modificata.2. Le Problematiche Architetturali ad Alto Livello e le loro SoluzioniSpostarsi su un modello ACM così flessibile introduce sfide uniche di governance, sincronizzazione e scalabilità.

Ecco le tre macro-problematiche concettuali e come risolverle a livello di design.Problematica 

A: Il "Disordine da Entropia" (Il Grafo a Spaghetti)

La Sfida: utenti diversi e agenti multipli che lavorano in parallelo sul Case creeranno relazioni arbitrarie, tag duplicati e ramificazioni caotiche. Il grafo rischia di diventare illeggibile sia per l'uomo che per l'LLM, inficiando la qualità del contesto.

<Sequence>
{/* Reason: Mostra come risolvere il disordine semantico attraverso l'applicazione di contratti di schema prima della scrittura nel grafo. */}
  <Step title="1. Proposta di Modifica" subtitle="L'agente/utente richiede un'azione">
    Un attore tenta di creare un nuovo nodo Task o una relazione nel caso.
  </Step>
  <Step title="2. Controllo di Conformità" subtitle="Il Guardrail dello Schema">
    Il sistema interseca la richiesta con le regole del nodo Base di dominio (es. sono ammessi solo i tipi di relazione definiti nel template di progetto).
  </Step>
  <Step title="3. Consolidamento Pulito" subtitle="Scrittura Transazionale">
    Se conforme, la modifica viene registrata. Se non conforme, il sistema forza l'uso di una multiselect strutturata o respinge la richiesta dell'LLM.
  </Step>
</Sequence>

La Soluzione Concettuale: Ereditarietà dei Template di Dominio e Vincoli di Schema.

I nodi Case devono ereditare regole da un "Meta-Modello di Dominio".
Se l'utente crea un caso di tipo "Esperimento AI", il sistema impone un vocabolario controllato per le relazioni (es. puoi usare solo [:DERIVED_FROM], [:RUNNED_BY], [:REQUIRES]).
La UI non permette l'inserimento a testo libero per i collegamenti strutturali, ma offre multiselect guidate, mentre l'LLM è controllato da un validatore formale (fail-closed) a livello di API di scrittura.

Problematica B: L'Allineamento dello Stato Fisico e Logico (Il Problema dei Fantasmi)

La Sfida: Gli artefatti (codebase, file pesanti) vivono nel filesystem o su repository Git esterni. Se uno sviluppatore modifica o elimina fisicamente una risorsa all'esterno della UI di ACM, il nodo Artifact nel grafo di Neo4j diventa un "fantasma" che punta al vuoto, portando l'LLM a allucinare su dati inesistenti.
La Soluzione Concettuale: OPERAZIONE BLOCANTE CON UN DEMONE, update che segue in caso di renaming o spostamento del path, oppure Riconciliazione Asincrona a Eventi (Heartbeat Semantico).Invece di tentare una sincronizzazione sincrona e bloccante (che distruggerebbe le performance), il sistema adotta un modello orientato agli eventi.
Ogni risorsa fisica esterna è registrata con un hash univoco di integrità. Un demone di background leggero (un watcher integrato con Git o con il filesystem) esegue controlli periodici di integrità. 
Se rileva una discrepanza:Non blocca l'utente. Emette un Event di tipo "Resource_Mutated" o "Resource_Missing" nel grafo. Cambia lo stato del nodo Artifact in ORPHAN o OUT_OF_SYNC.L'agente LLM, vedendo questo stato, adotta la politica predefinita (es. avvisa l'utente o propone un task di riallineamento).

Problematica C: La Saturazione Cognitiva dell'Agente (Token Overhead)

La Sfida: Man mano che le run di codice avanzano e i sotto-task si moltiplicano, il sotto-grafo del Case si espande a dismisura. Se l'agente deve consultare il grafo per pianificare il lavoro, l'invio dell'intera struttura genererà latenze inaccettabili e costi di token insostenibili.
La Soluzione Concettuale: Proiettori di Sotto-Grafi Attivi (Graph Focus Window).L'LLM non vede mai il grafo intero del caso. Il backend espone all'LLM dei tool di navigazione con "messa a fuoco" variabile:
Vista Orizzontale (La Mappa): Mostra solo i nodi Case, Stage e i Task principali attivi (stato IN_PROGRESS o TODO), ignorando la cronologia passata e i dettagli degli artefatti.Vista Verticale (Il Dettaglio): Se l'LLM deve lavorare su una specifica run di codice, il tool recupera solo quel singolo nodo Task, i suoi Artifact diretti e le sue Source.Filtro di Supersessione: Per impostazione predefinita, tutte le query del database escludono i nodi che hanno una relazione entrante di tipo [:SUPERSEDES], archiviando di fatto la cronologia logica dalla memoria a breve termine dell'agente.


## Valutazione critica dell' idea

Il percorso della conversazione parte da una critica al pattern "LLM Wiki" (file Markdown come knowledge base) ed evolve verso un'idea più matura: un **core a grafo (Neo4j) generico e agnostico**, sul quale si innestano **verticali operativi** (codebase runs, esperimenti LLM, knowledge management no-code) come *pacchetti di regole e schemi*, non come sistemi separati.

Questo è il punto di forza reale dell'idea: **non stai costruendo tre prodotti, ne stai costruendo uno solo con tre configurazioni**. Il rischio che however corri, e che va nominato esplicitamente, è che "generalista + estendibile" diventi la scusa per non decidere nulla in anticipo. Un motore che deve supportare "run di codice", "esperimenti ML" e "consulenti freelance" contemporaneamente ha vincoli di schema molto diversi tra loro; se il core è troppo permissivo, ogni verticale reinventerà le proprie convenzioni e il grafo tornerà a essere caotico quanto una cartella di file Markdown — semplicemente con un database più costoso sopra.

La soluzione non è "più libertà", è **un core minimo e rigido + verticali dichiarati come schema esplicito**, esattamente come atomicstrata/llm-wiki-compiler fa con i suoi contratti fail-closed. Questo è il filo conduttore che tiene insieme tutta l'evoluzione della conversazione, e va preservato nel design finale.

---

## Livello 1 — Il Core Generalista (Domain-Agnostic Graph Engine)

Indipendentemente dal verticale, ogni istanza del sistema condivide questi elementi invarianti:

- **Nodo `Base`**: entry point di un dominio (progetto, skill, task, cliente, esperimento). Ne esistono N, non uno solo — questo è il punto che rompe con l'LLM Wiki classico, dove esisteva un solo `index.md` monolitico.
- **Struttura a stella/DAG**: da ogni `Base` si dipartono relazioni verso nodi figli. Nessun ciclo, sempre navigabile in profondità limitata.
- **Ponti (relazioni) tipizzati**: le relazioni non sono testo libero, ma appartengono a un **set chiuso e versionato per verticale** (es. `DERIVED_FROM`, `RETRY_OF`, `RESUME_FROM`). La creazione di relazioni custom è ammessa solo come eccezione tracciata, non come default.
- **Doppio grafo attivo per interazione**: ad ogni query dell'agente si attivano *due* sotto-grafi — quello del contesto operativo corrente (progetto/task/esperimento) e quello del profilo/regole dell'utente (direttive, stile, vincoli). Questo è l'elemento più elegante emerso dalla conversazione: separa "cosa sto facendo" da "come devo comportarmi", evitando di dover reiniettare le preferenze ad ogni turno.
- **Backend ibrido**:
  - Neo4j → relazioni e metadati strutturali (leggero, mai contenuto pesante).
  - Postgres → contenuto, indicizzazione full-text/BM25, storicizzazione.
  - Filesystem/Git → file pesanti, codebase, versioning reale (mai reinventare i diff dentro il grafo).
- **Codice di condotta come nodo, non come file**: le istruzioni agentiche (l'equivalente di `CLAUDE.md`/`AGENTS.md`) sono un nodo `Base` di tipo regola, navigabile e componibile come qualunque altro nodo — non un file statico iniettato per intero nel prompt.

### Regola d'oro del core
Il core **non deve mai** esporre all'LLM il grafo intero. Ogni accesso passa da tool di *local search* (BFS a profondità limitata, query Cypher mirate, ricerca ibrida vettoriale+BM25 su Postgres). Il grafo intero esiste solo per gli strumenti di manutenzione (linting, community detection, merge), mai per il prompt runtime.

---

## Livello 2 — Wrapper Verticali (Domain Packages)

Un verticale è un **pacchetto dichiarativo** che estende il core con:
1. Sotto-tipi di nodo specifici (label aggiuntive su `Base`).
2. Un set chiuso di relazioni ammesse.
3. Regole di validazione fail-closed specifiche del dominio.
4. Politiche di sincronizzazione con risorse esterne (bloccante/non bloccante).

### Verticale A — Codebase Runs
- Nodi: `Run`, `Result`, `Environment`.
- Ponti: `RETRY_OF`, `DERIVED_FROM`.
- Criticità principale: senza un hash dell'ambiente di esecuzione (lockfile, container digest), due run identiche nel codice ma diverse nell'ambiente vengono trattate come equivalenti — falso positivo pericoloso in fase di analisi comparativa.
- Il codice va tracciato via Git, mai via diff salvati nel grafo: Neo4j conserva solo l'ID di commit.

### Verticale B — Esperimenti LLM
- Estende `Run` → `Experiment`, con nodi aggiuntivi `Checkpoint`, `Model`, `DataMix`, `Component`.
- Ponte esclusivo: `RESUME_FROM` per riprendere da un checkpoint nella stessa catena sperimentale.
- Criticità principale: i checkpoint sono spesso multi-GB. Il nodo deve contenere solo un puntatore logico (URI S3/storage), mai transitare il binario attraverso grafo o contesto del modello.

### Verticale C — Knowledge/Team No-Code (Consulente, Azienda)
- Nodi: `Progetto`, `Skill`, `Cliente`, `Documento/Link`.
- Ponti generati semi-automaticamente (proposta LLM economico + conferma utente in UI, mai relazione a mano libera come default).
- Criticità principale: **ereditarietà delle regole**. Con N progetti/clienti, le regole comuni (aziendali, di sicurezza, di stile) devono propagarsi da un nodo `Base` globale ai sotto-grafi, con possibilità di override locale esplicito — altrimenti si duplica la stessa informazione in ogni progetto, vanificando il vantaggio strutturale rispetto al Markdown piatto.

---

## Livello 3 — Adozione a Livelli Aziendali

Lo stesso core, la stessa infrastruttura, granularità diverse di deployment:

| Livello | Cosa cambia | Esempio pratico |
|---|---|---|
| Individuale | Un solo grafo utente, verticale libero (di solito Codebase Runs o Esperimenti) | Ricercatore che traccia i propri esperimenti ML |
| Team | Nodo `Base` team condiviso, eredità di regole verso i progetti dei singoli membri | Team che condivide convenzioni di stile e checkpoint di modello |
| Consulente/Cliente | Un `Base` per cliente, isolato ma con eredità da un `Base` "Studio/Azienda" | Consulente con 50 progetti, regole GDPR ereditate ovunque |
| Dipartimento/Azienda | Federazione di grafi (skill, progetti, compliance) con controllo accessi per sotto-grafo | Reparto R&D + reparto legale con visibilità incrociata solo su nodi specifici |

Il punto critico qui non è tecnico ma di governance: più si sale di livello, più serve un **controllo di accesso a grana fine sui sotto-grafi**, non solo sui nodi. Questo non era ancora emerso in conversazione ed è un rischio concreto in contesto aziendale (un consulente non deve poter navigare il sotto-grafo compliance di un altro cliente solo perché entrambi ereditano dallo stesso `Base` Studio).

---

## Rischi Trasversali (validi per ogni verticale)

1. **Grafo a spaghetti**: relazioni libere non tipizzate degradano la qualità del grafo esattamente come i wikilink liberi degradavano il Markdown. Mitigazione: set chiuso di relazioni per verticale, estensioni solo tracciate.
2. **Disallineamento grafo/risorsa esterna**: se un file o URI referenziato cambia fuori dal sistema, serve un watcher/trigger reale (non solo teorico) con politica esplicita di aggiornamento (bloccante vs asincrono).
3. **Cold start / disuso**: se la creazione dei ponti richiede troppo sforzo manuale, l'utente abbandona il sistema. La UI deve proporre, non richiedere, ogni collegamento.
4. **Fusione/summarization distruttiva**: qualunque operazione di merge o riassunto di nodi deve mantenere un puntatore ai nodi di dettaglio originali (struttura multi-risoluzione), mai sostituirli.
5. **Query dell'intero grafo nel prompt**: va vietato per policy di sistema, non lasciato alla disciplina dello sviluppatore del verticale.

---

## Sintesi

Il sistema non è "un altro LLM Wiki con Neo4j al posto di Markdown". È un motore a grafo minimale, con contratti di relazione rigidi, su cui si innestano verticali dichiarativi che ne specializzano nodi, relazioni e politiche di sincronizzazione — mantenendo sempre la separazione netta tra *contenuto pesante* (file/Git/Postgres) e *struttura relazionale* (Neo4j), e tra *contesto operativo* e *regole del profilo utente* come doppio grafo attivato ad ogni interazione.
