"""Default waterfall execution — 5-step loss allocation process.

The waterfall applies losses in order:
1. Defaulter's posted margin
2. Defaulter's default fund contribution
3. CCP equity (skin in the game)
4. Surviving members' default fund (pro-rata)
5. Loss allocation to surviving members (capped, pro-rata)

Each step creates balanced double-entry journal entries.
"""

import logging
import uuid
from decimal import Decimal

import psycopg

from ccp_shared.kafka.outbox import insert_outbox_event
from ccp_shared.trace import TraceContext

logger = logging.getLogger(__name__)


def execute_waterfall(
    conn: psycopg.Connection,
    member_id: str,
    trigger_reason: str,
    total_exposure: Decimal,
    trace: TraceContext | None = None,
) -> dict:
    """Execute the full default waterfall for a defaulting member.

    Args:
        conn: Database connection with ledger permissions.
        member_id: UUID of the defaulting member.
        trigger_reason: Human-readable reason for the default.
        total_exposure: Total loss amount to recover.

    Returns:
        Dict with default_event_id, steps executed, and final status.
    """
    if trace is None:
        trace = TraceContext.new_system("liquidation-engine")

    event_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO default_events (id, member_id, trigger_reason, total_exposure, status)
        VALUES (%s, %s, %s, %s, 'detected')
        """,
        (event_id, member_id, trigger_reason, total_exposure),
    )

    conn.execute(
        """
        UPDATE members SET status = 'defaulted', updated_at = now()
        WHERE id = %s
        """,
        (member_id,),
    )

    insert_outbox_event(
        conn,
        aggregate_type="default_event",
        aggregate_id=uuid.UUID(event_id),
        event_type="default.declared",
        topic="default.declared",
        payload={
            "default_event_id": event_id,
            "member_id": member_id,
            "trigger_reason": trigger_reason,
            "total_exposure": str(total_exposure),
        },
        trace_id=trace.trace_id,
    )

    remaining = total_exposure
    steps = []

    remaining, step = _step_defaulter_margin(conn, event_id, member_id, remaining, 1)
    steps.append(step)
    _update_event_status(conn, event_id, "margin_liquidated", trace)

    if remaining > Decimal("0"):
        remaining, step = _step_defaulter_default_fund(
            conn, event_id, member_id, remaining, 2,
        )
        steps.append(step)
        _update_event_status(conn, event_id, "default_fund_applied", trace)

    if remaining > Decimal("0"):
        remaining, step = _step_ccp_equity(conn, event_id, remaining, 3)
        steps.append(step)
        _update_event_status(conn, event_id, "ccp_equity_applied", trace)

    if remaining > Decimal("0"):
        remaining, step = _step_surviving_default_fund(
            conn, event_id, member_id, remaining, 4,
        )
        steps.append(step)
        _update_event_status(conn, event_id, "mutualized", trace)

    if remaining > Decimal("0"):
        remaining, step = _step_loss_allocation(
            conn, event_id, member_id, remaining, 5,
        )
        steps.append(step)

    final_status = "resolved" if remaining == Decimal("0") else "partially_resolved"
    conn.execute(
        """
        UPDATE default_events SET status = %s, resolved_at = now()
        WHERE id = %s
        """,
        (final_status, event_id),
    )

    insert_outbox_event(
        conn,
        aggregate_type="default_event",
        aggregate_id=uuid.UUID(event_id),
        event_type="default.resolved",
        topic="default.resolved",
        payload={
            "default_event_id": event_id,
            "status": final_status,
            "remaining_loss": str(remaining),
        },
        trace_id=trace.trace_id,
    )

    logger.info(
        "Waterfall complete: event=%s status=%s remaining=%s",
        event_id, final_status, remaining,
    )
    return {
        "default_event_id": event_id,
        "status": final_status,
        "steps": steps,
        "remaining_loss": str(remaining),
    }


def _step_defaulter_margin(
    conn: psycopg.Connection,
    event_id: str,
    member_id: str,
    remaining: Decimal,
    step_order: int,
) -> tuple[Decimal, dict]:
    """Step 1: Liquidate defaulter's posted margin."""
    available = _get_member_margin_balance(conn, member_id)
    applied = min(available, remaining)
    new_remaining = remaining - applied

    journal_id = None
    if applied > Decimal("0"):
        journal_id = _create_waterfall_journal(
            conn, event_id, member_id, applied, "MARGIN_IM",
        )

    step = _record_step(
        conn, event_id, step_order, "defaulter_margin",
        available, applied, new_remaining, journal_id,
    )
    return new_remaining, step


def _step_defaulter_default_fund(
    conn: psycopg.Connection,
    event_id: str,
    member_id: str,
    remaining: Decimal,
    step_order: int,
) -> tuple[Decimal, dict]:
    """Step 2: Use defaulter's default fund contribution."""
    available = _get_account_balance(conn, member_id, "DEFAULT_FUND", "AVAILABLE")
    applied = min(available, remaining)
    new_remaining = remaining - applied

    journal_id = None
    if applied > Decimal("0"):
        journal_id = _create_waterfall_journal(
            conn, event_id, member_id, applied, "DEFAULT_FUND",
        )

    step = _record_step(
        conn, event_id, step_order, "defaulter_default_fund",
        available, applied, new_remaining, journal_id,
    )
    return new_remaining, step


def _step_ccp_equity(
    conn: psycopg.Connection,
    event_id: str,
    remaining: Decimal,
    step_order: int,
) -> tuple[Decimal, dict]:
    """Step 3: CCP contributes its own equity."""
    ccp_id = _get_ccp_member_id(conn)
    available = Decimal("0")
    if ccp_id:
        available = _get_account_balance(conn, ccp_id, "CCP_EQUITY", "AVAILABLE")

    applied = min(available, remaining)
    new_remaining = remaining - applied

    journal_id = None
    if applied > Decimal("0") and ccp_id:
        journal_id = _create_waterfall_journal(
            conn, event_id, ccp_id, applied, "CCP_EQUITY",
        )

    step = _record_step(
        conn, event_id, step_order, "ccp_equity",
        available, applied, new_remaining, journal_id,
    )
    return new_remaining, step


def _step_surviving_default_fund(
    conn: psycopg.Connection,
    event_id: str,
    defaulter_id: str,
    remaining: Decimal,
    step_order: int,
) -> tuple[Decimal, dict]:
    """Step 4: Pro-rata mutualization from surviving members' default fund."""
    survivors = conn.execute(
        """
        SELECT m.id, ab.balance
        FROM members m
        JOIN accounts a ON a.member_id = m.id
            AND a.account_type = 'DEFAULT_FUND' AND a.pool = 'AVAILABLE'
        LEFT JOIN account_balances ab ON ab.account_id = a.id
        WHERE m.status = 'active' AND m.id != %s
            AND COALESCE(ab.balance, 0) > 0
        """,
        (defaulter_id,),
    ).fetchall()

    total_fund = sum(Decimal(str(s[1])) for s in survivors if s[1])
    total_applied = Decimal("0")

    if total_fund > Decimal("0"):
        for survivor_id, balance in survivors:
            bal = Decimal(str(balance)) if balance else Decimal("0")
            if bal <= Decimal("0"):
                continue
            share = (bal / total_fund) * remaining
            contribution = min(share, bal)
            if contribution > Decimal("0"):
                _create_waterfall_journal(
                    conn, event_id, str(survivor_id), contribution, "DEFAULT_FUND",
                )
                total_applied += contribution

    new_remaining = remaining - total_applied

    step = _record_step(
        conn, event_id, step_order, "surviving_members_default_fund",
        total_fund, total_applied, new_remaining, None,
    )
    return new_remaining, step


def _step_loss_allocation(
    conn: psycopg.Connection,
    event_id: str,
    defaulter_id: str,
    remaining: Decimal,
    step_order: int,
) -> tuple[Decimal, dict]:
    """Step 5: Loss allocation to surviving members (capped, pro-rata)."""
    survivors = conn.execute(
        """
        SELECT m.id, m.credit_limit
        FROM members m
        WHERE m.status = 'active' AND m.id != %s
        """,
        (defaulter_id,),
    ).fetchall()

    total_limits = sum(Decimal(str(s[1])) for s in survivors if s[1])
    total_applied = Decimal("0")

    if total_limits > Decimal("0"):
        for survivor_id, credit_limit in survivors:
            limit = Decimal(str(credit_limit)) if credit_limit else Decimal("0")
            if limit <= Decimal("0"):
                continue
            share = (limit / total_limits) * remaining
            cap = limit * Decimal("0.1")
            allocation = min(share, cap)
            if allocation > Decimal("0"):
                _create_waterfall_journal(
                    conn, event_id, str(survivor_id), allocation, "SETTLEMENT",
                )
                total_applied += allocation

    new_remaining = remaining - total_applied

    step = _record_step(
        conn, event_id, step_order, "loss_allocation",
        total_limits, total_applied, new_remaining, None,
    )
    return new_remaining, step


def _get_member_margin_balance(conn: psycopg.Connection, member_id: str) -> Decimal:
    """Get total posted margin (IM + VM, both pools) for a member."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(ab.balance), 0)
        FROM account_balances ab
        JOIN accounts a ON a.id = ab.account_id
        WHERE a.member_id = %s
          AND a.account_type IN ('MARGIN_IM', 'MARGIN_VM')
          AND ab.balance > 0
        """,
        (member_id,),
    ).fetchone()
    return Decimal(str(row[0])) if row and row[0] else Decimal("0")


def _get_account_balance(
    conn: psycopg.Connection,
    member_id: str,
    account_type: str,
    pool: str,
) -> Decimal:
    """Get balance for a specific account."""
    row = conn.execute(
        """
        SELECT COALESCE(ab.balance, 0)
        FROM account_balances ab
        JOIN accounts a ON a.id = ab.account_id
        WHERE a.member_id = %s AND a.account_type = %s AND a.pool = %s
        """,
        (member_id, account_type, pool),
    ).fetchone()
    return Decimal(str(row[0])) if row and row[0] else Decimal("0")


def _get_ccp_member_id(conn: psycopg.Connection) -> str | None:
    """Get the CCP house account member ID."""
    row = conn.execute(
        "SELECT id FROM members WHERE lei = 'CCP000000000000000'"
    ).fetchone()
    return str(row[0]) if row else None


def _create_waterfall_journal(
    conn: psycopg.Connection,
    event_id: str,
    member_id: str,
    amount: Decimal,
    source_account_type: str,
) -> str:
    """Create balanced journal entries for a waterfall step.

    Debits the member's source account (loss recovery) and credits
    a CCP recovery account.
    """
    member_acct = conn.execute(
        """
        SELECT id FROM accounts
        WHERE member_id = %s AND account_type = %s AND pool = 'AVAILABLE'
        """,
        (member_id, source_account_type),
    ).fetchone()

    ccp_id = _get_ccp_member_id(conn)
    ccp_acct = conn.execute(
        """
        SELECT id FROM accounts
        WHERE member_id = %s AND account_type = 'SETTLEMENT' AND pool = 'AVAILABLE'
        """,
        (ccp_id,),
    ).fetchone() if ccp_id else None

    journal_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
        VALUES (%s, 'DEFAULT_WATERFALL_STEP', 'default_event', %s, 'confirmed')
        """,
        (journal_id, event_id),
    )

    if member_acct:
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, str(member_acct[0]), amount),
        )
    if ccp_acct:
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, str(ccp_acct[0]), amount),
        )

    insert_outbox_event(
        conn,
        aggregate_type="default_event",
        aggregate_id=uuid.UUID(event_id),
        event_type="waterfall.step.executed",
        topic="waterfall.step.executed",
        payload={
            "default_event_id": event_id,
            "member_id": member_id,
            "amount": str(amount),
            "source": source_account_type,
            "journal_id": journal_id,
        },
    )

    return journal_id


def _record_step(
    conn: psycopg.Connection,
    event_id: str,
    step_order: int,
    step_type: str,
    available: Decimal,
    applied: Decimal,
    remaining: Decimal,
    journal_id: str | None,
) -> dict:
    """Record a waterfall step in the database."""
    step_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO waterfall_steps
            (id, default_event_id, step_order, step_type,
             available_amount, applied_amount, remaining_loss, journal_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (step_id, event_id, step_order, step_type,
         available, applied, remaining, journal_id),
    )
    return {
        "step_order": step_order,
        "step_type": step_type,
        "available": str(available),
        "applied": str(applied),
        "remaining": str(remaining),
    }


def _update_event_status(
    conn: psycopg.Connection,
    event_id: str,
    status: str,
    trace: TraceContext | None = None,
) -> None:
    """Update the default event status with trace context."""
    conn.execute(
        """
        INSERT INTO state_transitions
            (entity_type, entity_id, to_status, reason,
             transitioned_by, trace_id, actor)
        VALUES ('default_event', %s, %s, 'Waterfall step completed',
                %s, %s, %s)
        """,
        (
            event_id,
            status,
            f"liquidation-engine:{trace.actor}" if trace else "liquidation-engine",
            trace.trace_id if trace else None,
            trace.actor if trace else None,
        ),
    )
