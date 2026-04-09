"""Core novation logic for trade processing.

Validates incoming trades and performs novation -- splitting each
bilateral trade into two CCP-facing legs with margin locking.
"""

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

from ccp_shared.kafka.outbox import insert_outbox_event
from ccp_shared.trace import TraceContext

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when trade data fails validation checks."""


def validate_trade(conn: psycopg.Connection, trade_data: dict[str, Any]) -> None:
    """Validate trade data against member and instrument constraints.

    Args:
        conn: Open database connection.
        trade_data: Deserialized trade payload.

    Raises:
        ValidationError: If any validation check fails.
    """
    buyer_id = trade_data["buyer_member_id"]
    seller_id = trade_data["seller_member_id"]

    if buyer_id == seller_id:
        raise ValidationError("Buyer and seller must be different members")

    quantity = Decimal(str(trade_data["quantity"]))
    price = Decimal(str(trade_data["price"]))
    if quantity <= 0:
        raise ValidationError(f"Quantity must be positive, got {quantity}")
    if price <= 0:
        raise ValidationError(f"Price must be positive, got {price}")

    _verify_member_active(conn, buyer_id, "buyer")
    _verify_member_active(conn, seller_id, "seller")
    _verify_instrument_active(conn, trade_data["instrument_id"])


def _verify_member_active(
    conn: psycopg.Connection, member_id: str, role: str
) -> None:
    """Check that a member exists and is active."""
    row = conn.execute(
        "SELECT status FROM members WHERE id = %s",
        (member_id,),
    ).fetchone()
    if row is None:
        raise ValidationError(f"Member {role} {member_id} not found")
    if row[0] != "active":
        raise ValidationError(
            f"Member {role} {member_id} status is '{row[0]}', "
            f"expected 'active'"
        )


def _verify_instrument_active(
    conn: psycopg.Connection, instrument_id: str
) -> None:
    """Check that an instrument exists and is active."""
    row = conn.execute(
        "SELECT is_active FROM instruments WHERE id = %s",
        (instrument_id,),
    ).fetchone()
    if row is None:
        raise ValidationError(
            f"Instrument {instrument_id} not found"
        )
    if not row[0]:
        raise ValidationError(
            f"Instrument {instrument_id} is not active"
        )


def novate_trade(
    conn: psycopg.Connection,
    trade_id: UUID,
    trade_data: dict[str, Any],
    trace: TraceContext,
) -> dict[str, Any]:
    """Novate a validated trade into two CCP-facing legs.

    Args:
        conn: Open database connection (inside a transaction).
        trade_id: UUID of the original trade.
        trade_data: Deserialized trade payload.
        trace: Trace context for audit correlation.

    Returns:
        Dict with buyer_novated_id and seller_novated_id.

    Raises:
        ValidationError: If trade is not in 'submitted' status.
    """
    row = conn.execute(
        "SELECT status FROM trades WHERE id = %s",
        (str(trade_id),),
    ).fetchone()
    if row is None:
        raise ValidationError(f"Trade {trade_id} not found")
    if row[0] != "submitted":
        raise ValidationError(
            f"Trade {trade_id} cannot be novated: "
            f"status is '{row[0]}', expected 'submitted'"
        )

    conn.execute(
        "UPDATE trades SET status = 'novated', updated_at = now() "
        "WHERE id = %s",
        (str(trade_id),),
    )

    buyer_nov_id = _create_novated_trade(
        conn, trade_id, trade_data, "BUY",
        trade_data["buyer_member_id"],
    )
    seller_nov_id = _create_novated_trade(
        conn, trade_id, trade_data, "SELL",
        trade_data["seller_member_id"],
    )

    margin_rate = _fetch_margin_rate(conn, trade_data["instrument_id"])
    quantity = Decimal(str(trade_data["quantity"]))
    price = Decimal(str(trade_data["price"]))
    margin_amount = quantity * price * margin_rate

    _lock_margin(conn, trade_data["buyer_member_id"], buyer_nov_id, margin_amount)
    _lock_margin(conn, trade_data["seller_member_id"], seller_nov_id, margin_amount)

    _insert_state_transition(
        conn, "trade", trade_id, "submitted", "novated", trace,
    )
    _insert_state_transition(
        conn, "novated_trade", buyer_nov_id, None, "open", trace,
    )
    _insert_state_transition(
        conn, "novated_trade", seller_nov_id, None, "open", trace,
    )

    insert_outbox_event(
        conn,
        aggregate_type="trade",
        aggregate_id=trade_id,
        event_type="trade.novated",
        topic="trades.novated",
        payload={
            "trade_id": str(trade_id),
            "buyer_novated_id": str(buyer_nov_id),
            "seller_novated_id": str(seller_nov_id),
            "actor": trace.actor,
        },
        trace_id=trace.trace_id,
    )

    return {
        "buyer_novated_id": str(buyer_nov_id),
        "seller_novated_id": str(seller_nov_id),
    }


def _create_novated_trade(
    conn: psycopg.Connection,
    trade_id: UUID,
    trade_data: dict[str, Any],
    side: str,
    member_id: str,
) -> UUID:
    """Insert a novated trade leg and return its UUID."""
    row = conn.execute(
        """
        INSERT INTO novated_trades
            (original_trade_id, member_id, instrument_id,
             side, quantity, price)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            str(trade_id),
            member_id,
            trade_data["instrument_id"],
            side,
            str(trade_data["quantity"]),
            str(trade_data["price"]),
        ),
    ).fetchone()
    return UUID(str(row[0]))


def _fetch_margin_rate(
    conn: psycopg.Connection, instrument_id: str
) -> Decimal:
    """Fetch the initial margin rate for an instrument."""
    row = conn.execute(
        "SELECT margin_rate_im FROM instruments WHERE id = %s",
        (instrument_id,),
    ).fetchone()
    return Decimal(str(row[0]))


def _lock_margin(
    conn: psycopg.Connection,
    member_id: str,
    novated_trade_id: UUID,
    amount: Decimal,
) -> None:
    """Lock initial margin by journaling from AVAILABLE to LOCKED."""
    available_id = _find_account(conn, member_id, "MARGIN_IM", "AVAILABLE")
    locked_id = _find_account(conn, member_id, "MARGIN_IM", "LOCKED")

    journal_row = conn.execute(
        """
        INSERT INTO journals
            (journal_type, reference_type, reference_id, status)
        VALUES ('MARGIN_CALL', 'novated_trade', %s, 'confirmed')
        RETURNING id
        """,
        (str(novated_trade_id),),
    ).fetchone()
    journal_id = journal_row[0]

    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, %s, 0)
        """,
        (str(journal_id), str(available_id), str(amount)),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, 0, %s)
        """,
        (str(journal_id), str(locked_id), str(amount)),
    )


def _find_account(
    conn: psycopg.Connection,
    member_id: str,
    account_type: str,
    pool: str,
) -> UUID:
    """Look up a member's account by type and pool."""
    row = conn.execute(
        """
        SELECT id FROM accounts
        WHERE member_id = %s AND account_type = %s AND pool = %s
        """,
        (member_id, account_type, pool),
    ).fetchone()
    if row is None:
        raise ValidationError(
            f"No {account_type} {pool} account for member {member_id}"
        )
    return UUID(str(row[0]))


def _insert_state_transition(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
    from_status: str | None,
    to_status: str,
    trace: TraceContext,
) -> None:
    """Record a state transition with trace context."""
    conn.execute(
        """
        INSERT INTO state_transitions
            (entity_type, entity_id, from_status, to_status,
             transitioned_by, trace_id, actor)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            entity_type,
            str(entity_id),
            from_status,
            to_status,
            f"trade-ingestion:{trace.actor}",
            trace.trace_id,
            trace.actor,
        ),
    )


def process_trade(
    conn: psycopg.Connection,
    trade_data: dict[str, Any],
    trace: TraceContext | None = None,
) -> None:
    """Validate and novate a trade, or reject it on failure.

    Args:
        conn: Open database connection.
        trade_data: Deserialized trade payload including 'trade_id'.
        trace: Optional trace context for audit trails.
    """
    if trace is None:
        trace = TraceContext.new_system("trade-ingestion")
    trade_id = UUID(trade_data["trade_id"])
    try:
        validate_trade(conn, trade_data)
        with conn.transaction():
            novate_trade(conn, trade_id, trade_data, trace)
        logger.info("Trade %s novated successfully", trade_id)
    except (ValidationError, Exception) as exc:
        logger.warning("Trade %s failed: %s", trade_id, exc)
        _reject_trade(conn, trade_id, str(exc), trace)


def _reject_trade(
    conn: psycopg.Connection,
    trade_id: UUID,
    reason: str,
    trace: TraceContext,
) -> None:
    """Mark a trade as rejected and emit an outbox event."""
    with conn.transaction():
        conn.execute(
            "UPDATE trades SET status = 'rejected', updated_at = now() "
            "WHERE id = %s",
            (str(trade_id),),
        )
        _insert_state_transition(
            conn, "trade", trade_id, "submitted", "rejected", trace,
        )
        insert_outbox_event(
            conn,
            aggregate_type="trade",
            aggregate_id=trade_id,
            event_type="trade.rejected",
            topic="trades.rejected",
            payload={"trade_id": str(trade_id), "reason": reason},
            trace_id=trace.trace_id,
        )
