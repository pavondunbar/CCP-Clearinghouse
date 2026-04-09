"""Integration tests for the full trade lifecycle.

Tests trade submission through novation and netting, verifying
database state at each step. Requires PostgreSQL via testcontainers.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import psycopg

from ccp_shared.enums import NettingCycleType
from ccp_shared.trace import TraceContext
from netting_engine.netting import run_netting_cycle
from trade_ingestion.novation import novate_trade, validate_trade


def _insert_member(
    conn: psycopg.Connection,
    status: str = "active",
) -> str:
    """Insert a clearing member with accounts."""
    member_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO members (id, lei, name, status, credit_limit)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            member_id,
            f"LEI{uuid.uuid4().hex[:16].upper()}",
            "Test Member",
            status,
            Decimal("10000000"),
        ),
    )
    for acct_type in [
        "MARGIN", "SETTLEMENT", "DEFAULT_FUND", "COLLATERAL",
    ]:
        for pool in ["AVAILABLE", "LOCKED"]:
            conn.execute(
                """
                INSERT INTO accounts
                    (id, member_id, account_type, currency, pool)
                VALUES (%s, %s, %s, 'USD', %s)
                """,
                (
                    str(uuid.uuid4()),
                    member_id,
                    acct_type,
                    pool,
                ),
            )
    return member_id


def _insert_instrument(conn: psycopg.Connection) -> str:
    """Insert a test instrument."""
    inst_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO instruments
            (id, symbol, asset_class, settlement_type,
             margin_rate_im, margin_rate_vm, is_active)
        VALUES (%s, %s, 'crypto', 'cash', %s, %s, true)
        """,
        (
            inst_id,
            f"INT-{uuid.uuid4().hex[:6].upper()}",
            Decimal("0.1"),
            Decimal("0.05"),
        ),
    )
    return inst_id


def _insert_trade(
    conn: psycopg.Connection,
    buyer_id: str,
    seller_id: str,
    instrument_id: str,
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("50"),
) -> str:
    """Insert a trade and return its UUID."""
    trade_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO trades
            (id, external_trade_id, instrument_id,
             buyer_member_id, seller_member_id,
             quantity, price, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted')
        """,
        (
            trade_id,
            f"EXT-{uuid.uuid4().hex[:8]}",
            instrument_id,
            buyer_id,
            seller_id,
            quantity,
            price,
        ),
    )
    return trade_id


def _insert_price_feed(
    conn: psycopg.Connection,
    instrument_id: str,
    price: Decimal,
) -> None:
    """Insert a price feed record."""
    conn.execute(
        """
        INSERT INTO price_feeds
            (id, instrument_id, price, source, received_at)
        VALUES (%s, %s, %s, 'test', now())
        """,
        (str(uuid.uuid4()), instrument_id, price),
    )


def _insert_ccp_member(conn: psycopg.Connection) -> None:
    """Insert the CCP house member (zero UUID)."""
    ccp_id = "00000000-0000-0000-0000-000000000000"
    row = conn.execute(
        "SELECT id FROM members WHERE id = %s", (ccp_id,)
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        """
        INSERT INTO members (id, lei, name, status, credit_limit)
        VALUES (%s, 'CCPHOUSE000000000000', 'CCP House', 'active',
                0)
        """,
        (ccp_id,),
    )


class TestTradeSubmissionAndNovation:
    """Test trade submission through novation."""

    def test_trade_submission_and_novation(self, tx_conn):
        """Insert trade, run novation, verify all artifacts."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(tx_conn, buyer, seller, inst)

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        validate_trade(tx_conn, trade_data)
        trace = TraceContext.new_system("test")
        result = novate_trade(
            tx_conn, uuid.UUID(trade_id), trade_data, trace,
        )

        # Trade status updated to 'novated'
        status = tx_conn.execute(
            "SELECT status FROM trades WHERE id = %s",
            (trade_id,),
        ).fetchone()[0]
        assert status == "novated"

        # 2 novated_trades created
        nov_count = tx_conn.execute(
            """
            SELECT COUNT(*) FROM novated_trades
            WHERE original_trade_id = %s
            """,
            (trade_id,),
        ).fetchone()[0]
        assert nov_count == 2

        # Journal entries balance
        imbalanced = tx_conn.execute(
            """
            SELECT j.id
            FROM journals j
            JOIN journal_entries je ON je.journal_id = j.id
            GROUP BY j.id
            HAVING SUM(je.debit) != SUM(je.credit)
            """,
        ).fetchall()
        assert len(imbalanced) == 0

        # Outbox event created
        outbox = tx_conn.execute(
            """
            SELECT event_type FROM outbox_events
            WHERE aggregate_id = %s
            """,
            (trade_id,),
        ).fetchone()
        assert outbox is not None
        assert outbox[0] == "trade.novated"


class TestNovationThenNetting:
    """Test the full lifecycle from novation through netting."""

    def test_novation_then_netting(self, tx_conn):
        """Submit multiple trades, run netting, verify results."""
        _insert_ccp_member(tx_conn)
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        _insert_price_feed(tx_conn, inst, Decimal("50"))

        # Submit and novate two trades in opposite directions
        for qty, px in [
            (Decimal("100"), Decimal("50")),
            (Decimal("60"), Decimal("50")),
        ]:
            tid = _insert_trade(
                tx_conn, buyer, seller, inst, qty, px
            )
            trade_data = {
                "buyer_member_id": buyer,
                "seller_member_id": seller,
                "instrument_id": inst,
                "quantity": qty,
                "price": px,
            }
            trace = TraceContext.new_system("test")
            novate_trade(tx_conn, uuid.UUID(tid), trade_data, trace)

        cut_off = datetime.now(timezone.utc)
        result = run_netting_cycle(
            tx_conn,
            NettingCycleType.SCHEDULED,
            cut_off,
        )

        assert result["cycle_id"] is not None
        assert result["obligation_count"] > 0
        assert result["trades_netted"] > 0

        # Net obligations exist
        obl_count = tx_conn.execute(
            """
            SELECT COUNT(*) FROM net_obligations
            WHERE netting_cycle_id = %s
            """,
            (result["cycle_id"],),
        ).fetchone()[0]
        assert obl_count == result["obligation_count"]

        # Settlement instructions created
        si_count = tx_conn.execute(
            """
            SELECT COUNT(*) FROM settlement_instructions
            WHERE netting_cycle_id = %s
            """,
            (result["cycle_id"],),
        ).fetchone()[0]
        assert si_count == result["instruction_count"]

        # Novated trades marked as closed
        open_count = tx_conn.execute(
            """
            SELECT COUNT(*) FROM novated_trades
            WHERE status = 'open'
            """,
        ).fetchone()[0]
        assert open_count == 0
