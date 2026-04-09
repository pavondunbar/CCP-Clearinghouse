.PHONY: up down build migrate seed demo logs db-balances test lint format health health-docker clean topics query-topic

up:
	docker compose up -d

down:
	docker compose down

demo:
	python run_demo.py

logs:
	docker compose logs -f --tail=100

db-balances:
	docker compose exec postgres psql -U ccp_admin -d ccp_clearing -c \
		"SELECT m.name, a.account_type, a.pool, COALESCE(ab.balance, 0) AS balance \
		 FROM accounts a \
		 JOIN members m ON m.id = a.member_id \
		 LEFT JOIN account_balances ab ON ab.account_id = a.id \
		 WHERE COALESCE(ab.balance, 0) != 0 \
		 ORDER BY m.name, a.account_type, a.pool;"

build:
	docker build -t ccp-base:latest -f Dockerfile.base .
	docker compose build

migrate:
	docker compose exec api-gateway alembic -c /app/migrations/alembic.ini upgrade head

seed:
	docker compose exec api-gateway python /app/scripts/seed-members.py

test:
	uv run pytest tests/ -q

test-unit:
	uv run pytest tests/unit/ -q

test-integration:
	uv run pytest tests/integration/ -q

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

health:
	python scripts/health-check.py

health-docker:
	docker compose exec api-gateway python /app/scripts/health-check.py

clean:
	docker compose down -v --remove-orphans

topics:
	docker compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

query-topic:
	docker compose exec api-gateway python /app/scripts/query-topics.py $(ARGS)

monitoring-up:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

monitoring-down:
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down
