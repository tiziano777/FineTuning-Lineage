# ==============================================================================
# CONFIGURAZIONE REMOTI E BRANCH STATICI
# ==============================================================================
LOCAL_BRANCH  = main
GITHUB_REMOTE = all
GITLAB_REMOTE = origin
REQUIREMENT= NewRequirement-29534
# Messaggio di commit di default se non inserito a mano
m ?= "commit automatico: aggiornamento codice dpo-setup"

.PHONY: push-all 

## Aggiunge, committa e pusha su GitHub (main) e GitLab (branch dinamico)
push-all: 
	@echo "🚀 Preparazione file e commit..."
	@echo "----------------------------------------"
	
	# Sblocca la chiave SSH se necessario
	ssh-add ~/.ssh/lab_ssh 2>/dev/null || true
	
	# 1. Aggiunge le modifiche escludendo il Makefile
	git add .
	git reset Makefile
	
	# 2. Crea il commit (ignora l'errore se non ci sono nuove modifiche)
	git commit -m "$(m)" || echo "Nessuna nuova modifica da committare, procedo con il push."
	
	@echo "\n📤 Push su GitHub (${GITHUB_REMOTE}) sul branch [${LOCAL_BRANCH}]..."
	git push $(GITHUB_REMOTE) $(LOCAL_BRANCH) --force
	
	@echo "\n📤 Push su GitLab Aziendale (${GITLAB_REMOTE}) sul branch [$(REQUIREMENT)]..."
	# Invia il tuo main locale direttamente sul branch del requirement corrente su GitLab
	git push $(GITLAB_REMOTE) $(LOCAL_BRANCH):$(REQUIREMENT) --force
	
	@echo "----------------------------------------"
	@echo "✅ Sincronizzazione completata con successo sul requirement: $(REQUIREMENT)!"