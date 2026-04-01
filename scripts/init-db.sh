#!/usr/bin/env bash
set -euo pipefail

: "${POSTGRES_HOST:=localhost}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:=ccp_clearing}"
: "${POSTGRES_ADMIN_USER:=admin_user}"
: "${POSTGRES_ADMIN_PASSWORD:=admin_secret_change_me}"
: "${POSTGRES_LEDGER_USER:=ledger_user}"
: "${POSTGRES_LEDGER_PASSWORD:=ledger_secret_change_me}"
: "${POSTGRES_READONLY_USER:=readonly_user}"
: "${POSTGRES_READONLY_PASSWORD:=readonly_secret_change_me}"

PGCONN="postgresql://${POSTGRES_ADMIN_USER}:${POSTGRES_ADMIN_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}"
SQLA_CONN="postgresql+psycopg://${POSTGRES_ADMIN_USER}:${POSTGRES_ADMIN_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}"

echo "Waiting for PostgreSQL to be ready..."
until pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_ADMIN_USER" 2>/dev/null; do
    sleep 1
done

echo "Creating database if not exists..."
psql "${PGCONN}/postgres" -tc \
    "SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_DB}'" \
    | grep -q 1 \
    || psql "${PGCONN}/postgres" -c "CREATE DATABASE ${POSTGRES_DB}"

DB_CONN="${PGCONN}/${POSTGRES_DB}"

echo "Creating roles..."
psql "$DB_CONN" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_READONLY_USER}') THEN
        CREATE ROLE ${POSTGRES_READONLY_USER} LOGIN PASSWORD '${POSTGRES_READONLY_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_LEDGER_USER}') THEN
        CREATE ROLE ${POSTGRES_LEDGER_USER} LOGIN PASSWORD '${POSTGRES_LEDGER_PASSWORD}';
    END IF;
END
\$\$;
SQL

echo "Running Alembic migrations..."
DATABASE_URL="${SQLA_CONN}/${POSTGRES_DB}" alembic -c /app/migrations/alembic.ini upgrade head

echo "Granting permissions to readonly_user..."
psql "$DB_CONN" <<SQL
GRANT USAGE ON SCHEMA public TO ${POSTGRES_READONLY_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${POSTGRES_READONLY_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO ${POSTGRES_READONLY_USER};
SQL

echo "Granting permissions to ledger_user..."
psql "$DB_CONN" <<SQL
GRANT USAGE ON SCHEMA public TO ${POSTGRES_LEDGER_USER};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${POSTGRES_LEDGER_USER};
GRANT INSERT ON journals, journal_entries, trades, novated_trades,
    accounts, margin_requirements, margin_calls, netting_cycles,
    net_obligations, settlement_instructions, state_transitions,
    price_feeds, default_events, waterfall_steps, outbox_events
    TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (published_at) ON outbox_events TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, updated_at) ON trades TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, updated_at) ON novated_trades TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, updated_at) ON margin_calls TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, completed_at) ON netting_cycles TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, updated_at, tx_hash, block_number, confirmations)
    ON settlement_instructions TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, resolved_at) ON default_events TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (status, updated_at, credit_limit) ON members TO ${POSTGRES_LEDGER_USER};
GRANT UPDATE (required_amount, posted_amount, calculated_at)
    ON margin_requirements TO ${POSTGRES_LEDGER_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO ${POSTGRES_LEDGER_USER};
SQL

echo "Database initialization complete."
