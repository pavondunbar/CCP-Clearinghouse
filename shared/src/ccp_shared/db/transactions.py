"""Transaction management with journal balance validation."""

from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal

import psycopg

from ccp_shared.errors import LedgerImbalanceError


@contextmanager
def ledger_transaction(
    conn: psycopg.Connection,
) -> Generator[psycopg.Connection, None, None]:
    """Context manager that wraps a ledger operation in a transaction.

    On exit, validates that all journal entries created within the
    transaction have balanced debits and credits before committing.
    Rolls back on any exception or imbalance.

    Args:
        conn: An open psycopg Connection.

    Yields:
        The connection within an active transaction.

    Raises:
        LedgerImbalanceError: If debits and credits do not balance.
    """
    with conn.transaction() as tx:
        yield conn
        _validate_journal_balance(conn, tx)


def _validate_journal_balance(
    conn: psycopg.Connection,
    tx: psycopg.Transaction,
) -> None:
    """Check that pending journal entries within the transaction balance.

    Queries for any journals in 'pending' status where the sum of
    debit entries does not equal the sum of credit entries.

    Args:
        conn: The active connection.
        tx: The current transaction (used for context in errors).

    Raises:
        LedgerImbalanceError: If any journal has unbalanced entries.
    """
    cursor = conn.execute("""
        SELECT
            j.id AS journal_id,
            COALESCE(SUM(
                CASE WHEN je.direction = 'debit'
                THEN je.amount ELSE 0 END
            ), 0) AS debit_sum,
            COALESCE(SUM(
                CASE WHEN je.direction = 'credit'
                THEN je.amount ELSE 0 END
            ), 0) AS credit_sum
        FROM journals j
        JOIN journal_entries je ON je.journal_id = j.id
        WHERE j.status = 'pending'
        GROUP BY j.id
        HAVING COALESCE(SUM(
            CASE WHEN je.direction = 'debit'
            THEN je.amount ELSE 0 END
        ), 0) != COALESCE(SUM(
            CASE WHEN je.direction = 'credit'
            THEN je.amount ELSE 0 END
        ), 0)
    """)
    row = cursor.fetchone()
    if row is not None:
        journal_id, debit_sum, credit_sum = row
        raise LedgerImbalanceError(
            f"Journal {journal_id} imbalanced: "
            f"debits={debit_sum}, credits={credit_sum}",
            journal_id=journal_id,
            debit_sum=Decimal(str(debit_sum)),
            credit_sum=Decimal(str(credit_sum)),
        )
