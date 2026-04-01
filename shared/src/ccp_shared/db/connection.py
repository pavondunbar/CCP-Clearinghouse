"""Database connection helpers for CCP Clearing House."""

import psycopg

from ccp_shared.config import CCPSettings


def get_connection(dsn: str) -> psycopg.Connection:
    """Open a synchronous PostgreSQL connection.

    Args:
        dsn: PostgreSQL connection string.

    Returns:
        An open psycopg Connection.
    """
    return psycopg.connect(dsn, autocommit=False)


def get_ledger_connection(
    settings: CCPSettings,
) -> psycopg.Connection:
    """Open a connection using the ledger user credentials.

    Args:
        settings: CCP configuration with database credentials.

    Returns:
        An open psycopg Connection for ledger operations.
    """
    return get_connection(settings.ledger_dsn())


def get_readonly_connection(
    settings: CCPSettings,
) -> psycopg.Connection:
    """Open a connection using the read-only user credentials.

    Args:
        settings: CCP configuration with database credentials.

    Returns:
        An open psycopg Connection for read-only queries.
    """
    return get_connection(settings.readonly_dsn())
