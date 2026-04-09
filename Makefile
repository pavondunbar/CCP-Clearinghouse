.DEFAULT_GOAL := help

.PHONY: help up down restart build clean ps \
        demo test test-unit test-integration test-e2e \
        logs health health-docker integrity monitoring-up monitoring-down \
        db-balances db-ledger db-rtgs shell-pg migrate seed seed-accounts \
        topics kafka-tail query-topic shell-kafka \
        lint format open-docs

# ── Help ────────────────────────────────────────────────────

help:
	@echo "CCP Clearing House"
	@echo ""
	@echo "Lifecycle:"
	@echo "  up                Start all containers"
	@echo "  down              Stop all containers"
	@echo "  restart           Restart all containers"
	@echo "  build             Build base image and all services"
	@echo "  clean             Stop containers and delete volumes"
	@echo "  ps                Show container status"
	@echo ""
	@echo "Demo & Testing:"
	@echo "  demo              Run full clearing lifecycle demo"
	@echo "  test              Run all tests"
	@echo "  test-unit         Run unit tests only"
	@echo "  test-integration  Run integration tests (testcontainers)"
	@echo "  test-e2e          Run end-to-end demo against live stack"
	@echo ""
	@echo "Observability:"
	@echo "  logs              Tail all service logs"
	@echo "  health            Check service health (local)"
	@echo "  health-docker     Check service health (in-container)"
	@echo "  integrity         Run ledger reconciliation check"
	@echo "  monitoring-up     Start Prometheus + Grafana"
	@echo "  monitoring-down   Stop Prometheus + Grafana"
	@echo ""
	@echo "Database:"
	@echo "  db-balances       Show non-zero account balances"
	@echo "  db-ledger         Show recent journal entries"
	@echo "  db-rtgs           Show settlement instructions"
	@echo "  shell-pg          Open interactive psql shell"
	@echo "  migrate           Run Alembic migrations"
	@echo "  seed              Seed members, instruments, accounts"
	@echo "  seed-accounts     Alias for seed"
	@echo ""
	@echo "Kafka:"
	@echo "  topics            List all Kafka topics"
	@echo "  kafka-tail        Tail a topic (TOPIC=<name>)"
	@echo "  query-topic       Query topic messages (ARGS=...)"
	@echo "  shell-kafka       Open Kafka container shell"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint              Run ruff linter"
	@echo "  format            Auto-format with ruff"
	@echo ""
	@echo "Docs:"
	@echo "  open-docs         Open API docs in browser"

# ── Lifecycle ───────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

build:
	docker build -t ccp-base:latest -f Dockerfile.base .
	docker compose build

clean:
	docker compose down -v --remove-orphans

ps:
	docker compose ps

# ── Demo & Testing ──────────────────────────────────────────

demo:
	python run_demo.py

test:
	uv run pytest tests/ -q

test-unit:
	uv run pytest tests/unit/ -q

test-integration:
	uv run pytest tests/integration/ -q

test-e2e:
	python run_demo.py

# ── Observability ───────────────────────────────────────────

logs:
	docker compose logs -f --tail=100

health:
	python scripts/health-check.py

health-docker:
	docker compose exec api-gateway python /app/scripts/health-check.py

integrity:
	@curl -sf -X POST http://localhost:8000/reconcile \
		-H "Content-Type: application/json" -d '{}' \
		| python -m json.tool

monitoring-up:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

monitoring-down:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down

# ── Database ────────────────────────────────────────────────

db-balances:
	docker compose exec postgres psql -U admin_user -d ccp_clearing -c \
		"SELECT m.name, a.account_type, a.pool, COALESCE(ab.balance, 0) AS balance \
		 FROM accounts a \
		 JOIN members m ON m.id = a.member_id \
		 LEFT JOIN account_balances ab ON ab.account_id = a.id \
		 WHERE COALESCE(ab.balance, 0) != 0 \
		 ORDER BY m.name, a.account_type, a.pool;"

db-ledger:
	docker compose exec postgres psql -U admin_user -d ccp_clearing -c \
		"SELECT j.journal_type, je.account_id, je.debit, je.credit, je.created_at \
		 FROM journal_entries je \
		 JOIN journals j ON j.id = je.journal_id \
		 ORDER BY je.created_at DESC \
		 LIMIT 30;"

db-rtgs:
	docker compose exec postgres psql -U admin_user -d ccp_clearing -c \
		"SELECT id, settlement_type, status, chain_id, tx_hash, created_at \
		 FROM settlement_instructions \
		 ORDER BY created_at DESC \
		 LIMIT 20;"

shell-pg:
	docker compose exec postgres psql -U admin_user -d ccp_clearing

migrate:
	docker compose exec api-gateway alembic -c /app/migrations/alembic.ini upgrade head

seed:
	docker compose run --rm seed-data

seed-accounts: seed

# ── Kafka ───────────────────────────────────────────────────

topics:
	docker compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

kafka-tail:
	docker compose exec kafka kafka-console-consumer \
		--bootstrap-server localhost:9092 \
		--topic $(TOPIC) \
		--from-beginning \
		--max-messages 50

query-topic:
	docker compose exec api-gateway python /app/scripts/query-topics.py $(ARGS)

shell-kafka:
	docker compose exec kafka bash

# ── Code Quality ────────────────────────────────────────────

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

# ── Docs ────────────────────────────────────────────────────

open-docs:
	open http://localhost:8000/docs
