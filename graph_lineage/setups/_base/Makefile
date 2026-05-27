.PHONY: train lint test setup

# Activate venv and run training
train:
	python train.py

# Lint
lint:
	ruff check .

# Test
test:
	pytest tests/ -v

# Start Neo4j (requires docker)
neo4j-up:
	docker compose up neo4j -d

# Full stack
setup: neo4j-up
	pip install -e ".[dev]"
	@echo "Ready. Run 'make train' to start."
