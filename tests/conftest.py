"""Shared test fixtures using testcontainers for PostgreSQL and Kafka."""

import os
import uuid
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(scope="session")
def pg_container():
    """Start a PostgreSQL 16 container for the test session."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver=None) as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_url(pg_container) -> str:
    """Return the PostgreSQL connection URL."""
    return pg_container.get_connection_url()


@pytest.fixture(scope="session")
def _run_migrations(pg_url: str) -> None:
    """Run all Alembic migrations against the test database."""
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", pg_url)
    alembic_cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def db_conn(
    pg_url: str,
    _run_migrations: None,
) -> Generator[psycopg.Connection, None, None]:
    """Provide a session-scoped database connection with migrations applied."""
    with psycopg.connect(pg_url) as conn:
        yield conn


@pytest.fixture()
def tx_conn(
    pg_url: str,
    _run_migrations: None,
) -> Generator[psycopg.Connection, None, None]:
    """Provide a per-test connection that rolls back after each test."""
    with psycopg.connect(pg_url) as conn:
        conn.autocommit = False
        yield conn
        conn.rollback()


@pytest.fixture()
def sample_member(tx_conn: psycopg.Connection) -> dict:
    """Create a sample clearing member with all account types."""
    member_id = str(uuid.uuid4())
    tx_conn.execute(
        """
        INSERT INTO members (id, lei, name, status, credit_limit)
        VALUES (%s, %s, %s, 'active', %s)
        """,
        (member_id, f"LEI{uuid.uuid4().hex[:16].upper()}", "Test Member", Decimal("10000000")),
    )

    account_ids = {}
    for acct_type in ["MARGIN_IM", "MARGIN_VM", "DEFAULT_FUND", "COLLATERAL", "SETTLEMENT"]:
        for pool in ["AVAILABLE", "LOCKED"]:
            acct_id = str(uuid.uuid4())
            tx_conn.execute(
                """
                INSERT INTO accounts (id, member_id, account_type, currency, pool)
                VALUES (%s, %s, %s, 'USD', %s)
                """,
                (acct_id, member_id, acct_type, pool),
            )
            account_ids[f"{acct_type}_{pool}"] = acct_id

    return {"member_id": member_id, "accounts": account_ids}


@pytest.fixture()
def sample_instrument(tx_conn: psycopg.Connection) -> dict:
    """Create a sample instrument."""
    inst_id = str(uuid.uuid4())
    tx_conn.execute(
        """
        INSERT INTO instruments (id, symbol, asset_class, settlement_type,
                                 margin_rate_im, margin_rate_vm)
        VALUES (%s, %s, 'crypto_perpetual', 'cash', %s, %s)
        """,
        (inst_id, f"TEST-{uuid.uuid4().hex[:6].upper()}", Decimal("0.1"), Decimal("0.05")),
    )
    return {
        "instrument_id": inst_id,
        "margin_rate_im": Decimal("0.1"),
        "margin_rate_vm": Decimal("0.05"),
    }
