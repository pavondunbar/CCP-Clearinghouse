"""Core reconciliation logic: replay ledger, recompute, compare."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg

logger = logging.getLogger(__name__)


@dataclass
class AccountResult:
    """Per-account reconciliation result."""

    account_id: str
    expected_balance: Decimal
    actual_balance: Decimal
    difference: Decimal
    status: str


@dataclass
class ReconciliationReport:
    """Full reconciliation report."""

    status: str = "pass"
    global_balance_ok: bool = True
    journal_integrity_ok: bool = True
    accounts_checked: int = 0
    mismatches: int = 0
    details: list[AccountResult] = field(default_factory=list)


def check_global_balance(conn: psycopg.Connection) -> bool:
    """Verify total system debits equal total system credits.

    Args:
        conn: Read-only database connection.

    Returns:
        True if debits == credits across all confirmed journals.
    """
    row = conn.execute(
        """
        SELECT SUM(je.debit) AS total_debits,
               SUM(je.credit) AS total_credits
        FROM journal_entries je
        JOIN journals j ON j.id = je.journal_id
        WHERE j.status = 'confirmed'
        """
    ).fetchone()
    if row is None or row[0] is None:
        return True
    return row[0] == row[1]


def check_journal_integrity(conn: psycopg.Connection) -> bool:
    """Verify every confirmed journal has balanced entries.

    Args:
        conn: Read-only database connection.

    Returns:
        True if all journals are balanced (debits == credits).
    """
    row = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT j.id
            FROM journals j
            JOIN journal_entries je ON je.journal_id = j.id
            WHERE j.status = 'confirmed'
            GROUP BY j.id
            HAVING SUM(je.debit) != SUM(je.credit)
        ) unbalanced
        """
    ).fetchone()
    return row is not None and row[0] == 0


def run_reconciliation(
    conn: psycopg.Connection,
) -> ReconciliationReport:
    """Run full reconciliation: replay ledger, recompute, compare.

    Queries all confirmed journal entries, recomputes balances
    from scratch, then compares against the account_balances
    derived view.

    Args:
        conn: Read-only database connection.

    Returns:
        ReconciliationReport with per-account results.
    """
    global_ok = check_global_balance(conn)
    journal_ok = check_journal_integrity(conn)

    recomputed_rows = conn.execute(
        """
        SELECT je.account_id,
               SUM(je.debit) - SUM(je.credit) AS computed
        FROM journal_entries je
        JOIN journals j ON j.id = je.journal_id
        WHERE j.status = 'confirmed'
        GROUP BY je.account_id
        """
    ).fetchall()

    actual_balances: dict[str, Decimal] = {}
    for row in conn.execute(
        "SELECT account_id, balance FROM account_balances"
    ).fetchall():
        actual_balances[str(row[0])] = (
            Decimal(str(row[1])) if row[1] is not None else Decimal("0")
        )

    details: list[AccountResult] = []
    mismatches = 0

    for row in recomputed_rows:
        account_id = str(row[0])
        expected = Decimal(str(row[1]))
        actual = actual_balances.get(account_id, Decimal("0"))
        diff = expected - actual
        acct_status = "ok" if diff == 0 else "mismatch"
        if diff != 0:
            mismatches += 1
            logger.warning(
                "Balance mismatch: account=%s expected=%s actual=%s diff=%s",
                account_id, expected, actual, diff,
            )
        details.append(AccountResult(
            account_id=account_id,
            expected_balance=expected,
            actual_balance=actual,
            difference=diff,
            status=acct_status,
        ))

    overall = (
        "pass"
        if mismatches == 0 and global_ok and journal_ok
        else "fail"
    )

    report = ReconciliationReport(
        status=overall,
        global_balance_ok=global_ok,
        journal_integrity_ok=journal_ok,
        accounts_checked=len(recomputed_rows),
        mismatches=mismatches,
        details=details,
    )

    logger.info(
        "Reconciliation complete: status=%s checked=%d mismatches=%d",
        overall, len(recomputed_rows), mismatches,
    )
    return report
