"""Margin calculation engine for initial and variation margin."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg

from ccp_shared.config import CCPSettings
from ccp_shared.kafka.outbox import insert_outbox_event
from ccp_shared.trace import TraceContext

logger = logging.getLogger(__name__)


def calculate_initial_margin(
    net_quantity: Decimal,
    latest_price: Decimal,
    margin_rate_im: Decimal,
) -> Decimal:
    """Calculate initial margin requirement.

    Args:
        net_quantity: Net position quantity (can be negative).
        latest_price: Current market price.
        margin_rate_im: Initial margin rate for the instrument.

    Returns:
        Required initial margin amount (always positive).
    """
    return abs(net_quantity) * latest_price * margin_rate_im


def calculate_variation_margin(
    net_quantity: Decimal,
    current_price: Decimal,
    previous_mark: Decimal,
) -> Decimal:
    """Calculate variation margin (mark-to-market P&L).

    Args:
        net_quantity: Net position quantity (positive=long, negative=short).
        current_price: Current market price.
        previous_mark: Previous mark/settlement price.

    Returns:
        VM amount (positive = member owes, negative = member receives).
    """
    return (current_price - previous_mark) * net_quantity


def recalculate_margins(
    conn: psycopg.Connection,
    settings: CCPSettings,
    trace: TraceContext | None = None,
) -> list[dict]:
    """Recalculate IM and VM for all member-instrument positions.

    Fetches current positions, latest prices, and updates margin
    requirements. Issues margin calls for any shortfalls.

    Args:
        conn: Database connection with ledger permissions.
        settings: Application settings.
        trace: Optional trace context for audit correlation.

    Returns:
        List of margin call dicts issued during this recalculation.
    """
    if trace is None:
        trace = TraceContext.new_system("margin-engine")
    margin_calls = []

    positions = conn.execute(
        """
        SELECT mp.member_id, mp.instrument_id,
               mp.net_quantity, mp.avg_price,
               i.margin_rate_im, i.margin_rate_vm,
               lp.price AS latest_price
        FROM member_positions mp
        JOIN instruments i ON i.id = mp.instrument_id
        LEFT JOIN latest_prices lp ON lp.instrument_id = mp.instrument_id
        WHERE mp.net_quantity != 0
        """
    ).fetchall()

    for pos in positions:
        member_id, instrument_id = pos[0], pos[1]
        net_qty, avg_price = pos[2], pos[3]
        rate_im, rate_vm = pos[4], pos[5]
        latest_price = pos[6] or avg_price

        im_required = calculate_initial_margin(net_qty, latest_price, rate_im)
        _update_margin_requirement(
            conn, member_id, instrument_id, "INITIAL", im_required,
        )

        vm_amount = calculate_variation_margin(net_qty, latest_price, avg_price)
        if vm_amount != Decimal("0"):
            _process_variation_margin(conn, member_id, instrument_id, vm_amount)

        shortfall = _check_shortfall(conn, member_id, instrument_id, "INITIAL")
        if shortfall > Decimal("0"):
            call = _issue_margin_call(
                conn, settings, member_id, instrument_id, shortfall, trace,
            )
            margin_calls.append(call)

    return margin_calls


def _update_margin_requirement(
    conn: psycopg.Connection,
    member_id: str,
    instrument_id: str,
    margin_type: str,
    required_amount: Decimal,
) -> None:
    """Upsert a margin requirement record."""
    conn.execute(
        """
        INSERT INTO margin_requirements
            (member_id, instrument_id, margin_type, required_amount)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (member_id, instrument_id, margin_type)
        DO UPDATE SET required_amount = EXCLUDED.required_amount,
                      calculated_at = now()
        """,
        (member_id, instrument_id, margin_type, required_amount),
    )


def _get_account_id(
    conn: psycopg.Connection,
    member_id: str,
    account_type: str,
    pool: str,
) -> str | None:
    """Look up an account ID by member, type, and pool."""
    row = conn.execute(
        """
        SELECT id FROM accounts
        WHERE member_id = %s AND account_type = %s AND pool = %s
        """,
        (member_id, account_type, pool),
    ).fetchone()
    return str(row[0]) if row else None


def _process_variation_margin(
    conn: psycopg.Connection,
    member_id: str,
    instrument_id: str,
    vm_amount: Decimal,
) -> None:
    """Create journal entries for variation margin transfer."""
    vm_available = _get_account_id(conn, member_id, "MARGIN_VM", "AVAILABLE")
    vm_locked = _get_account_id(conn, member_id, "MARGIN_VM", "LOCKED")
    if not vm_available or not vm_locked:
        logger.warning("VM accounts not found for member %s", member_id)
        return

    journal_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
        VALUES (%s, 'VARIATION_MARGIN', 'margin_requirement', %s, 'confirmed')
        """,
        (journal_id, instrument_id),
    )

    abs_amount = abs(vm_amount)
    if vm_amount > Decimal("0"):
        debit_acct, credit_acct = vm_available, vm_locked
    else:
        debit_acct, credit_acct = vm_locked, vm_available

    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, %s, 0)
        """,
        (journal_id, debit_acct, abs_amount),
    )
    conn.execute(
        """
        INSERT INTO journal_entries (journal_id, account_id, debit, credit)
        VALUES (%s, %s, 0, %s)
        """,
        (journal_id, credit_acct, abs_amount),
    )

    _update_margin_requirement(conn, member_id, instrument_id, "VARIATION", abs_amount)


def _check_shortfall(
    conn: psycopg.Connection,
    member_id: str,
    instrument_id: str,
    margin_type: str,
) -> Decimal:
    """Check margin shortfall for a specific requirement."""
    row = conn.execute(
        """
        SELECT shortfall FROM margin_requirements
        WHERE member_id = %s AND instrument_id = %s AND margin_type = %s
        """,
        (member_id, instrument_id, margin_type),
    ).fetchone()
    return Decimal(str(row[0])) if row and row[0] else Decimal("0")


def _issue_margin_call(
    conn: psycopg.Connection,
    settings: CCPSettings,
    member_id: str,
    instrument_id: str,
    shortfall: Decimal,
    trace: TraceContext,
) -> dict:
    """Issue a margin call for a member's shortfall."""
    deadline = datetime.now(timezone.utc) + timedelta(
        minutes=settings.margin_call_deadline_minutes
    )
    call_id = str(uuid.uuid4())

    req_row = conn.execute(
        """
        SELECT id FROM margin_requirements
        WHERE member_id = %s AND instrument_id = %s AND margin_type = 'INITIAL'
        """,
        (member_id, instrument_id),
    ).fetchone()

    conn.execute(
        """
        INSERT INTO margin_calls
            (id, member_id, margin_requirement_id, call_amount, deadline, status)
        VALUES (%s, %s, %s, %s, %s, 'issued')
        """,
        (call_id, member_id, str(req_row[0]) if req_row else None, shortfall, deadline),
    )

    conn.execute(
        """
        INSERT INTO state_transitions
            (entity_type, entity_id, to_status, reason,
             transitioned_by, trace_id, actor)
        VALUES ('margin_call', %s, 'issued',
                'Margin shortfall detected', %s, %s, %s)
        """,
        (
            call_id,
            f"margin-engine:{trace.actor}",
            trace.trace_id,
            trace.actor,
        ),
    )

    payload = {
        "margin_call_id": call_id,
        "member_id": member_id,
        "instrument_id": instrument_id,
        "call_amount": str(shortfall),
        "deadline": deadline.isoformat(),
        "margin_type": "INITIAL",
    }
    insert_outbox_event(
        conn,
        aggregate_type="margin_call",
        aggregate_id=uuid.UUID(call_id),
        event_type="margin.call.issued",
        topic="margin.call.issued",
        payload=payload,
        trace_id=trace.trace_id,
    )

    logger.info(
        "Margin call %s issued: member=%s amount=%s deadline=%s",
        call_id, member_id, shortfall, deadline,
    )
    return payload
