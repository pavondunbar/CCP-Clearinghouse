"""Collateral operations: deposit, withdraw, and pool transfers."""

import logging
import uuid
from decimal import Decimal

import psycopg

from ccp_shared.errors import InsufficientMarginError, ValidationError
from ccp_shared.kafka.outbox import insert_outbox_event

logger = logging.getLogger(__name__)


def deposit_collateral(
    conn: psycopg.Connection,
    member_id: str,
    amount: Decimal,
    currency: str = "USD",
) -> dict:
    """Record a collateral deposit for a clearing member.

    Creates balanced journal entries debiting the member's collateral
    available account and crediting the CCP's settlement account.

    Args:
        conn: Database connection with ledger permissions.
        member_id: UUID of the depositing member.
        amount: Deposit amount (must be positive).
        currency: Currency code.

    Returns:
        Dict with journal_id and deposit details.
    """
    if amount <= Decimal("0"):
        raise ValidationError("Deposit amount must be positive")

    member_acct = _get_account(conn, member_id, "COLLATERAL", "AVAILABLE", currency)
    ccp_acct = _get_ccp_account(conn, "SETTLEMENT", "AVAILABLE", currency)
    if not member_acct or not ccp_acct:
        raise ValidationError(f"Accounts not found for member {member_id}")

    journal_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
        VALUES (%s, 'COLLATERAL_DEPOSIT', 'member', %s, 'confirmed')
        """,
        (journal_id, member_id),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, %s, 0)
        """,
        (journal_id, member_acct, amount),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, 0, %s)
        """,
        (journal_id, ccp_acct, amount),
    )

    insert_outbox_event(
        conn,
        aggregate_type="collateral",
        aggregate_id=uuid.UUID(member_id),
        event_type="collateral.deposited",
        topic="collateral.deposited",
        payload={
            "member_id": member_id,
            "amount": str(amount),
            "currency": currency,
            "journal_id": journal_id,
        },
    )

    logger.info("Collateral deposit: member=%s amount=%s", member_id, amount)
    return {"journal_id": journal_id, "member_id": member_id, "amount": str(amount)}


def withdraw_collateral(
    conn: psycopg.Connection,
    member_id: str,
    amount: Decimal,
    currency: str = "USD",
) -> dict:
    """Process a collateral withdrawal for a clearing member.

    Validates sufficient available balance before creating reverse
    journal entries.

    Args:
        conn: Database connection with ledger permissions.
        member_id: UUID of the withdrawing member.
        amount: Withdrawal amount (must be positive).
        currency: Currency code.

    Returns:
        Dict with journal_id and withdrawal details.
    """
    if amount <= Decimal("0"):
        raise ValidationError("Withdrawal amount must be positive")

    member_acct = _get_account(conn, member_id, "COLLATERAL", "AVAILABLE", currency)
    if not member_acct:
        raise ValidationError(f"Collateral account not found for member {member_id}")

    balance = _get_balance(conn, member_acct)
    if balance < amount:
        raise InsufficientMarginError(
            message=f"Insufficient collateral: available={balance}, requested={amount}",
            member_id=member_id,
            required=amount,
            available=balance,
        )

    ccp_acct = _get_ccp_account(conn, "SETTLEMENT", "AVAILABLE", currency)
    if not ccp_acct:
        raise ValidationError("CCP settlement account not found")

    journal_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
        VALUES (%s, 'COLLATERAL_WITHDRAWAL', 'member', %s, 'confirmed')
        """,
        (journal_id, member_id),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, 0, %s)
        """,
        (journal_id, member_acct, amount),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, %s, 0)
        """,
        (journal_id, ccp_acct, amount),
    )

    insert_outbox_event(
        conn,
        aggregate_type="collateral",
        aggregate_id=uuid.UUID(member_id),
        event_type="collateral.withdrawn",
        topic="collateral.withdrawn",
        payload={
            "member_id": member_id,
            "amount": str(amount),
            "currency": currency,
            "journal_id": journal_id,
        },
    )

    logger.info("Collateral withdrawal: member=%s amount=%s", member_id, amount)
    return {"journal_id": journal_id, "member_id": member_id, "amount": str(amount)}


def transfer_to_margin(
    conn: psycopg.Connection,
    member_id: str,
    amount: Decimal,
    margin_type: str = "MARGIN_IM",
) -> dict:
    """Move collateral from available to margin account.

    Used when responding to margin calls — transfers from COLLATERAL
    AVAILABLE to the specified MARGIN account AVAILABLE pool.

    Args:
        conn: Database connection with ledger permissions.
        member_id: UUID of the member.
        amount: Transfer amount.
        margin_type: Target margin account type (MARGIN_IM or MARGIN_VM).

    Returns:
        Dict with journal_id and transfer details.
    """
    if amount <= Decimal("0"):
        raise ValidationError("Transfer amount must be positive")

    collateral_acct = _get_account(conn, member_id, "COLLATERAL", "AVAILABLE")
    margin_acct = _get_account(conn, member_id, margin_type, "AVAILABLE")
    if not collateral_acct or not margin_acct:
        raise ValidationError(f"Accounts not found for member {member_id}")

    balance = _get_balance(conn, collateral_acct)
    if balance < amount:
        raise InsufficientMarginError(
            message=f"Insufficient collateral for margin transfer",
            member_id=member_id,
            required=amount,
            available=balance,
        )

    journal_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
        VALUES (%s, 'COLLATERAL_DEPOSIT', 'margin_call', %s, 'confirmed')
        """,
        (journal_id, member_id),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, 0, %s)
        """,
        (journal_id, collateral_acct, amount),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, %s, 0)
        """,
        (journal_id, margin_acct, amount),
    )

    _update_posted_margin(conn, member_id, margin_type, amount)

    return {"journal_id": journal_id, "member_id": member_id, "amount": str(amount)}


def _get_account(
    conn: psycopg.Connection,
    member_id: str,
    account_type: str,
    pool: str,
    currency: str = "USD",
) -> str | None:
    """Look up an account ID."""
    row = conn.execute(
        """
        SELECT id FROM accounts
        WHERE member_id = %s AND account_type = %s
          AND pool = %s AND currency = %s
        """,
        (member_id, account_type, pool, currency),
    ).fetchone()
    return str(row[0]) if row else None


def _get_ccp_account(
    conn: psycopg.Connection,
    account_type: str,
    pool: str,
    currency: str = "USD",
) -> str | None:
    """Look up a CCP house account ID."""
    row = conn.execute(
        """
        SELECT a.id FROM accounts a
        JOIN members m ON m.id = a.member_id
        WHERE m.lei = 'CCP000000000000000'
          AND a.account_type = %s AND a.pool = %s AND a.currency = %s
        """,
        (account_type, pool, currency),
    ).fetchone()
    return str(row[0]) if row else None


def _get_balance(conn: psycopg.Connection, account_id: str) -> Decimal:
    """Get the current balance from the account_balances view."""
    row = conn.execute(
        "SELECT balance FROM account_balances WHERE account_id = %s",
        (account_id,),
    ).fetchone()
    return Decimal(str(row[0])) if row and row[0] else Decimal("0")


def _update_posted_margin(
    conn: psycopg.Connection,
    member_id: str,
    margin_type: str,
    amount: Decimal,
) -> None:
    """Update posted_amount on margin requirements after collateral transfer."""
    conn.execute(
        """
        UPDATE margin_requirements
        SET posted_amount = posted_amount + %s
        WHERE member_id = %s AND margin_type = %s
        """,
        (amount, member_id, margin_type),
    )
