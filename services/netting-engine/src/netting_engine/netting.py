"""Multilateral netting algorithm for CCP Clearing House.

Computes net obligations across members and instruments, then
generates settlement instructions for the resulting positions.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from ccp_shared.enums import (
    NettingCycleStatus,
    NettingCycleType,
    SettlementInstructionStatus,
    SettlementType,
    StateEntityType,
)
from ccp_shared.kafka.outbox import insert_outbox_event
from ccp_shared.trace import TraceContext

logger = logging.getLogger(__name__)

CCP_LEI = "CCP000000000000000"


def _get_ccp_member_id(conn: psycopg.Connection) -> str:
    """Look up the CCP house account member ID by LEI."""
    row = conn.execute(
        "SELECT id FROM members WHERE lei = %s",
        (CCP_LEI,),
    ).fetchone()
    if row is None:
        raise RuntimeError("CCP House Account not found in members table")
    return str(row[0])


def calculate_net_obligations(
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute net obligations from aggregated position data.

    Pure function with no database dependency. For each
    (member_id, instrument_id) pair, nets buy and sell quantities
    and computes the settlement amount.

    Args:
        positions: List of dicts with keys: member_id,
            instrument_id, side, total_quantity, total_value,
            latest_price, settlement_type.

    Returns:
        List of net obligation dicts with keys: member_id,
        instrument_id, net_quantity, net_amount,
        settlement_amount, settlement_type.
    """
    grouped: dict[tuple[str, str], dict[str, Decimal]] = {}

    for pos in positions:
        key = (pos["member_id"], pos["instrument_id"])
        if key not in grouped:
            grouped[key] = {
                "buy_qty": Decimal("0"),
                "sell_qty": Decimal("0"),
                "latest_price": pos.get(
                    "latest_price", Decimal("0")
                ),
                "settlement_type": pos.get(
                    "settlement_type", SettlementType.CASH.value
                ),
            }
        if pos["side"] == "BUY":
            grouped[key]["buy_qty"] += Decimal(
                str(pos["total_quantity"])
            )
        else:
            grouped[key]["sell_qty"] += Decimal(
                str(pos["total_quantity"])
            )
        if pos.get("latest_price") is not None:
            grouped[key]["latest_price"] = Decimal(
                str(pos["latest_price"])
            )

    obligations: list[dict[str, Any]] = []
    for (member_id, instrument_id), data in grouped.items():
        net_qty = data["buy_qty"] - data["sell_qty"]
        if net_qty == Decimal("0"):
            continue
        net_amount = net_qty * data["latest_price"]
        obligations.append({
            "member_id": member_id,
            "instrument_id": instrument_id,
            "net_quantity": net_qty,
            "net_amount": net_amount,
            "settlement_amount": abs(net_amount),
            "settlement_type": data["settlement_type"],
        })

    return obligations


def _fetch_open_positions(
    conn: psycopg.Connection,
    cut_off_time: datetime,
) -> list[dict[str, Any]]:
    """Query aggregated open novated trade positions.

    Args:
        conn: Active database connection.
        cut_off_time: Only include trades novated at or before.

    Returns:
        List of position dicts grouped by member/instrument/side.
    """
    rows = conn.execute(
        """
        SELECT nt.member_id, nt.instrument_id, nt.side,
               SUM(nt.quantity) AS total_quantity,
               SUM(nt.quantity * nt.price) AS total_value
        FROM novated_trades nt
        WHERE nt.status = 'open'
          AND nt.novated_at <= %s
        GROUP BY nt.member_id, nt.instrument_id, nt.side
        """,
        (cut_off_time,),
    ).fetchall()

    positions: list[dict[str, Any]] = []
    for row in rows:
        positions.append({
            "member_id": str(row[0]),
            "instrument_id": str(row[1]),
            "side": row[2],
            "total_quantity": row[3],
            "total_value": row[4],
        })
    return positions


def _enrich_with_prices(
    conn: psycopg.Connection,
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add latest_price and settlement_type to each position.

    Args:
        conn: Active database connection.
        positions: Position dicts to enrich.

    Returns:
        The same list with latest_price and settlement_type added.
    """
    instrument_ids = {p["instrument_id"] for p in positions}
    if not instrument_ids:
        return positions

    placeholders = ", ".join(["%s"] * len(instrument_ids))
    rows = conn.execute(
        f"""
        SELECT i.id,
               (SELECT pf.price FROM price_feeds pf
                WHERE pf.instrument_id = i.id
                ORDER BY pf.received_at DESC LIMIT 1),
               i.settlement_type
        FROM instruments i
        WHERE i.id IN ({placeholders})
        """,
        tuple(instrument_ids),
    ).fetchall()

    price_map: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        price = row[1] if row[1] is not None else Decimal("0")
        price_map[str(row[0])] = (Decimal(str(price)), row[2])

    for pos in positions:
        inst_id = pos["instrument_id"]
        if inst_id in price_map:
            pos["latest_price"] = price_map[inst_id][0]
            pos["settlement_type"] = price_map[inst_id][1]
        else:
            pos["latest_price"] = Decimal("0")
            pos["settlement_type"] = SettlementType.CASH.value

    return positions


def _insert_obligations_and_instructions(
    conn: psycopg.Connection,
    cycle_id: str,
    obligations: list[dict[str, Any]],
    ccp_member_id: str,
) -> list[str]:
    """Insert net obligations and settlement instructions.

    Args:
        conn: Active database connection.
        cycle_id: UUID of the netting cycle.
        obligations: Computed net obligation dicts.
        ccp_member_id: UUID of the CCP house account.

    Returns:
        List of settlement instruction UUIDs created.
    """
    instruction_ids: list[str] = []

    for obl in obligations:
        obl_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO net_obligations
                (id, netting_cycle_id, member_id, instrument_id,
                 net_quantity, net_amount, settlement_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                obl_id,
                cycle_id,
                obl["member_id"],
                obl["instrument_id"],
                obl["net_quantity"],
                obl["net_amount"],
                obl["settlement_amount"],
            ),
        )

        instr_id = str(uuid.uuid4())
        if obl["net_amount"] > Decimal("0"):
            from_member = obl["member_id"]
            to_member = ccp_member_id
        else:
            from_member = ccp_member_id
            to_member = obl["member_id"]

        stype = obl["settlement_type"]

        conn.execute(
            """
            INSERT INTO settlement_instructions
                (id, netting_cycle_id, from_member_id,
                 to_member_id, instrument_id, quantity,
                 amount, settlement_type, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                instr_id,
                cycle_id,
                from_member,
                to_member,
                obl["instrument_id"],
                abs(obl["net_quantity"]),
                obl["settlement_amount"],
                stype,
                SettlementInstructionStatus.PENDING.value,
            ),
        )
        instruction_ids.append(instr_id)

    return instruction_ids


def _mark_trades_closed(
    conn: psycopg.Connection,
    cut_off_time: datetime,
) -> int:
    """Mark included novated trades as netted after netting.

    Args:
        conn: Active database connection.
        cut_off_time: Trades novated at or before this time.

    Returns:
        Number of trades marked as netted.
    """
    cursor = conn.execute(
        """
        UPDATE novated_trades
        SET status = 'netted'
        WHERE status = 'open' AND novated_at <= %s
        """,
        (cut_off_time,),
    )
    return cursor.rowcount


def _record_state_transition(
    conn: psycopg.Connection,
    entity_id: str,
    entity_type: str,
    from_status: str,
    to_status: str,
    trace: TraceContext | None = None,
) -> None:
    """Insert a state transition record with optional trace context.

    Args:
        conn: Active database connection.
        entity_id: UUID of the entity.
        entity_type: Type of entity (e.g., 'netting_cycle').
        from_status: Previous status value.
        to_status: New status value.
        trace: Optional trace context for audit correlation.
    """
    conn.execute(
        """
        INSERT INTO state_transitions
            (id, entity_type, entity_id, from_status, to_status,
             transitioned_by, trace_id, actor)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid.uuid4()),
            entity_type,
            entity_id,
            from_status,
            to_status,
            f"netting-engine:{trace.actor}" if trace else "netting-engine",
            trace.trace_id if trace else None,
            trace.actor if trace else None,
        ),
    )


def run_netting_cycle(
    conn: psycopg.Connection,
    cycle_type: NettingCycleType,
    cut_off_time: datetime,
    trace: TraceContext | None = None,
) -> dict[str, Any]:
    """Execute a full multilateral netting cycle.

    Runs inside a single database transaction. Creates a netting
    cycle, computes net obligations, generates settlement
    instructions, and publishes outbox events.

    Args:
        conn: Active database connection (autocommit=False).
        cycle_type: Type of netting cycle being run.
        cut_off_time: Include trades novated at or before.
        trace: Optional trace context for audit correlation.

    Returns:
        Dict with cycle_id, obligation_count,
        instruction_count, and trades_netted.
    """
    if trace is None:
        trace = TraceContext.new_system("netting-engine")

    cycle_id = str(uuid.uuid4())

    with conn.transaction():
        conn.execute(
            """
            INSERT INTO netting_cycles (id, cycle_type, status, cut_off_time)
            VALUES (%s, %s, %s, %s)
            """,
            (
                cycle_id,
                cycle_type.value,
                NettingCycleStatus.INITIATED.value,
                cut_off_time,
            ),
        )

        _record_state_transition(
            conn, cycle_id,
            StateEntityType.NETTING_CYCLE.value,
            NettingCycleStatus.INITIATED.value,
            NettingCycleStatus.CALCULATING.value,
            trace,
        )
        conn.execute(
            "UPDATE netting_cycles SET status = %s WHERE id = %s",
            (NettingCycleStatus.CALCULATING.value, cycle_id),
        )

        ccp_member_id = _get_ccp_member_id(conn)

        positions = _fetch_open_positions(conn, cut_off_time)
        positions = _enrich_with_prices(conn, positions)
        obligations = calculate_net_obligations(positions)

        instruction_ids = _insert_obligations_and_instructions(
            conn, cycle_id, obligations, ccp_member_id
        )

        trades_netted = _mark_trades_closed(conn, cut_off_time)

        _record_state_transition(
            conn, cycle_id,
            StateEntityType.NETTING_CYCLE.value,
            NettingCycleStatus.CALCULATING.value,
            NettingCycleStatus.CONFIRMED.value,
            trace,
        )
        conn.execute(
            "UPDATE netting_cycles SET status = %s WHERE id = %s",
            (NettingCycleStatus.CONFIRMED.value, cycle_id),
        )

        insert_outbox_event(
            conn,
            aggregate_type="netting_cycle",
            aggregate_id=uuid.UUID(cycle_id),
            event_type="netting.cycle.completed",
            topic="netting.cycle.completed",
            payload={
                "cycle_id": cycle_id,
                "cycle_type": cycle_type.value,
                "obligation_count": len(obligations),
                "trades_netted": trades_netted,
            },
            trace_id=trace.trace_id,
        )

        for instr_id in instruction_ids:
            insert_outbox_event(
                conn,
                aggregate_type="settlement_instruction",
                aggregate_id=uuid.UUID(instr_id),
                event_type="settlement.instruction.created",
                topic="settlement.instructions.created",
                payload={
                    "instruction_id": instr_id,
                    "cycle_id": cycle_id,
                },
                trace_id=trace.trace_id,
            )

    logger.info(
        "Netting cycle %s completed: %d obligations, "
        "%d instructions, %d trades netted",
        cycle_id,
        len(obligations),
        len(instruction_ids),
        trades_netted,
    )

    return {
        "cycle_id": cycle_id,
        "obligation_count": len(obligations),
        "instruction_count": len(instruction_ids),
        "trades_netted": trades_netted,
    }
