.PHONY: help master-up master-down master-logs master-test master-shell master-reset neo4j-shell streamlit-up streamlit-down streamlit-logs streamlit-shell stack-up stack-down health-check

streamlit-ui:
	@echo "🚀 Starting Streamlit UI..."
	docker-compose up -d streamlit
	@echo "✅ Streamlit started on http://localhost:8501"

streamlit-rebuild:
	@echo "🔨 Rebuilding Streamlit UI..."
	docker-compose build streamlit && docker-compose up -d streamlit
	@echo "✅ Streamlit rebuilt"

streamlit-rollback:
	@echo "⏪ Rolling back Streamlit UI to previous image..."
	docker-compose down -v streamlit && docker-compose build streamlit &&  docker-compose up -d streamlit
	@echo "✅ Streamlit rolled back to latest image"

help:
	@echo "FineTuning Lineage System — Master Infrastructure"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Master Targets:"
	@echo "  master-up          Start Master services (Neo4j + Phoenix + Master API)"
	@echo "  master-down        Stop Master services gracefully"
	@echo "  master-reset       Stop Master and remove volumes (⚠️ data loss)"
	@echo "  master-logs        Stream logs from Master services"
	@echo "  master-logs-neo4j  Stream logs from Neo4j only"
	@echo "  master-logs-phoenix Stream logs from Phoenix only"
	@echo "  master-logs-api    Stream logs from Master API only"
	@echo "  master-test        Run lineage tests with Docker (requires master-up)"
	@echo "  master-shell       Open shell in Neo4j container"
	@echo "  master-status      Show Master service status"
	@echo ""
	@echo "Streamlit Targets:"
	@echo "  streamlit-up       Start Streamlit UI container"
	@echo "  streamlit-down     Stop Streamlit UI container"
	@echo "  streamlit-logs     Stream logs from Streamlit"
	@echo "  streamlit-shell    Open shell in Streamlit container"
	@echo ""
	@echo "Stack Targets:"
	@echo "  stack-up           Start all services (Neo4j + Phoenix + Master + Streamlit)"
	@echo "  stack-down         Stop all services gracefully"
	@echo "  health-check       Verify all services are healthy"
	@echo ""

master-up:
	@echo "🚀 Starting Master infrastructure..."
	docker-compose -f docker-compose.yml up -d
	@echo "✅ Services started"
	@echo ""
	@echo "Access points:"
	@echo "  Neo4j Browser: http://localhost:7474 (neo4j/password)"
	@echo "  Phoenix UI:    http://localhost:6006"
	@echo "  Master API:    http://localhost:8000"
	@echo ""

master-down:
	@echo "⏹️  Stopping Master infrastructure..."
	docker-compose -f docker-compose.yml down
	@echo "✅ Services stopped"

master-reset:
	@echo "🔄 Resetting Master infrastructure (removing volumes)..."
	docker-compose -f docker-compose.yml down -v
	@echo "✅ Services stopped and volumes removed"

master-logs:
	docker-compose -f docker-compose.yml logs -f

master-logs-neo4j:
	docker-compose -f docker-compose.yml logs -f neo4j

master-logs-phoenix:
	docker-compose -f docker-compose.yml logs -f phoenix

master-logs-api:
	docker-compose -f docker-compose.yml logs -f master-api

master-status:
	@docker-compose -f docker-compose.yml ps

neo4j-shell:
	@echo "Opening Neo4j cypher-shell..."
	docker exec -it lineage-neo4j cypher-shell -u neo4j -p password

master-test:
	@echo "🧪 Running Phase 2 lineage tests with Docker..."
	source .venv/bin/activate && python -m pytest tests/lineage/ -v --tb=short
	@echo "✅ Tests complete"

# Testing shortcuts
test-constraints:
	source .venv/bin/activate && python -m pytest tests/lineage/test_constraints.py -v

test-triggers:
	source .venv/bin/activate && python -m pytest tests/lineage/test_apoc_triggers.py -v

test-driver:
	source .venv/bin/activate && python -m pytest tests/lineage/test_neo4j_driver.py -v

test-repository:
	source .venv/bin/activate && python -m pytest tests/lineage/test_repository_impl.py tests/lineage/test_repository_advanced.py -v

# Development helpers
lint:
	source .venv/bin/activate && ruff check . --fix

format:
	source .venv/bin/activate && ruff format .

type-check:
	source .venv/bin/activate && python -m mypy master/ --ignore-missing-imports

dev-setup:
	pip install -e ".[dev,test,master]"

# CI targets
streamlit-up:
	@echo "🚀 Starting Streamlit UI..."
	docker-compose up -d streamlit
	@echo "✅ Streamlit started on http://localhost:8501"

streamlit-down:
	@echo "⏹️  Stopping Streamlit..."
	docker-compose down streamlit
	@echo "✅ Streamlit stopped"

streamlit-logs:
	docker-compose logs -f streamlit

streamlit-shell:
	docker-compose exec streamlit /bin/bash

stack-up:
	@echo "🚀 Starting full stack (Neo4j + Phoenix + Master API + Streamlit)..."
	docker-compose up -d
	@echo "✅ Full stack started"
	@echo ""
	@echo "Access points:"
	@echo "  Neo4j Browser:    http://localhost:7474 (neo4j/password)"
	@echo "  Phoenix UI:       http://localhost:6006"
	@echo "  Master API:       http://localhost:8000"
	@echo "  Streamlit UI:     http://localhost:8501"

stack-down:
	@echo "⏹️  Stopping full stack..."
	docker-compose down
	@echo "✅ Full stack stopped"

health-check:
	@echo "🏥 Checking service health..."
	@echo ""
	@echo "Neo4j:"
	docker-compose exec -T neo4j cypher-shell -u neo4j -p password "RETURN 1" && echo "✓ Neo4j OK" || echo "✗ Neo4j FAILED"
	@echo ""
	@echo "Master API:"
	curl -s http://localhost:8000/health && echo -e "\n✓ Master API OK" || echo "✗ Master API FAILED"
	@echo ""
	@echo "Streamlit:"
	curl -s http://localhost:8501/_stcore/health && echo -e "\n✓ Streamlit OK" || echo "✗ Streamlit FAILED"

# CI targets
ci-test: master-up test-constraints test-triggers test-driver test-repository
	@echo "✅ All tests passed"

ci-lint: lint format
	@echo "✅ Linting passed"


