"""Unit tests for trade novation logic.

Tests validation rules and novation behavior using the database
via the tx_conn fixture (auto-rolled-back per test).
"""

import uuid
from decimal import Decimal

import psycopg
import pytest

from ccp_shared.trace import TraceContext
from trade_ingestion.novation import (
    ValidationError,
    novate_trade,
    validate_trade,
)


def _insert_member(
    conn: psycopg.Connection,
    status: str = "active",
) -> str:
    """Insert a test member and return its UUID string."""
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
    _create_accounts(conn, member_id)
    return member_id


def _create_accounts(
    conn: psycopg.Connection,
    member_id: str,
) -> None:
    """Create standard account set for a member."""
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
                (str(uuid.uuid4()), member_id, acct_type, pool),
            )


def _insert_instrument(
    conn: psycopg.Connection,
    is_active: bool = True,
) -> str:
    """Insert a test instrument and return its UUID string."""
    inst_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO instruments
            (id, symbol, asset_class, settlement_type,
             margin_rate_im, margin_rate_vm, is_active)
        VALUES (%s, %s, 'crypto', 'cash', %s, %s, %s)
        """,
        (
            inst_id,
            f"TEST-{uuid.uuid4().hex[:6].upper()}",
            Decimal("0.1"),
            Decimal("0.05"),
            is_active,
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
    """Insert a trade record and return its UUID string."""
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


class TestNovationCreatesTrades:
    """Test that novation produces two CCP-facing legs."""

    def test_novation_creates_two_novated_trades(self, tx_conn):
        """Novation should produce exactly 2 novated trades."""
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

        trace = TraceContext.new_system("test")
        result = novate_trade(
            tx_conn, uuid.UUID(trade_id), trade_data, trace,
        )

        rows = tx_conn.execute(
            """
            SELECT id, side FROM novated_trades
            WHERE original_trade_id = %s
            ORDER BY side
            """,
            (trade_id,),
        ).fetchall()

        assert len(rows) == 2
        sides = {row[1] for row in rows}
        assert sides == {"BUY", "SELL"}
        assert "buyer_novated_id" in result
        assert "seller_novated_id" in result


class TestNovationMarginLock:
    """Test that novation locks the correct margin amount."""

    def test_novation_margin_lock_amount(self, tx_conn):
        """margin_amount = quantity * price * margin_rate_im."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(
            tx_conn, buyer, seller, inst,
            quantity=Decimal("100"), price=Decimal("50"),
        )

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        trace = TraceContext.new_system("test")
        novate_trade(tx_conn, uuid.UUID(trade_id), trade_data, trace)

        # margin_rate_im = 0.1, so margin = 100 * 50 * 0.1 = 500
        rows = tx_conn.execute(
            """
            SELECT SUM(je.debit) AS total_debit
            FROM journal_entries je
            JOIN journals j ON j.id = je.journal_id
            WHERE j.journal_type = 'MARGIN_CALL'
              AND je.debit > 0
            """,
        ).fetchone()
        # Two members, each locks 500 => total debit = 1000
        assert rows[0] == Decimal("1000")


class TestNovationJournalBalance:
    """Test that journal entries always balance."""

    def test_novation_journal_entries_balance(self, tx_conn):
        """For each journal, sum(debit) == sum(credit)."""
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

        trace = TraceContext.new_system("test")
        novate_trade(tx_conn, uuid.UUID(trade_id), trade_data, trace)

        rows = tx_conn.execute(
            """
            SELECT j.id,
                   SUM(je.debit) AS debits,
                   SUM(je.credit) AS credits
            FROM journals j
            JOIN journal_entries je ON je.journal_id = j.id
            GROUP BY j.id
            """,
        ).fetchall()

        assert len(rows) > 0
        for row in rows:
            assert row[1] == row[2], (
                f"Journal {row[0]} unbalanced: "
                f"debit={row[1]}, credit={row[2]}"
            )


class TestNovationValidation:
    """Test novation validation rejects invalid inputs."""

    def test_novation_rejects_inactive_member(self, tx_conn):
        """Should raise ValidationError for inactive member."""
        buyer = _insert_member(tx_conn, status="suspended")
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        with pytest.raises(ValidationError, match="active"):
            validate_trade(tx_conn, trade_data)

    def test_novation_rejects_same_buyer_seller(self, tx_conn):
        """Should raise ValidationError when buyer == seller."""
        member = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)

        trade_data = {
            "buyer_member_id": member,
            "seller_member_id": member,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        with pytest.raises(ValidationError, match="different"):
            validate_trade(tx_conn, trade_data)

    def test_novation_rejects_zero_quantity(self, tx_conn):
        """Should raise ValidationError for zero quantity."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("0"),
            "price": Decimal("50"),
        }

        with pytest.raises(ValidationError, match="positive"):
            validate_trade(tx_conn, trade_data)

    def test_novation_rejects_nonexistent_instrument(
        self, tx_conn
    ):
        """Should raise ValidationError for unknown instrument."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": str(uuid.uuid4()),
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        with pytest.raises(ValidationError, match="not found"):
            validate_trade(tx_conn, trade_data)


class TestNovationStateTransitions:
    """Test that novation rejects trades not in 'submitted' status."""

    def test_novate_already_novated_trade_rejected(self, tx_conn):
        """Cannot novate a trade that has already been novated."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(tx_conn, buyer, seller, inst)
        trace = TraceContext.new_system("test")

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        novate_trade(tx_conn, uuid.UUID(trade_id), trade_data, trace)

        with pytest.raises(ValidationError, match="novated"):
            novate_trade(
                tx_conn, uuid.UUID(trade_id), trade_data, trace,
            )

    def test_novate_rejected_trade_rejected(self, tx_conn):
        """Cannot novate a trade that has been rejected."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(tx_conn, buyer, seller, inst)

        tx_conn.execute(
            "UPDATE trades SET status = 'rejected' WHERE id = %s",
            (trade_id,),
        )

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }
        trace = TraceContext.new_system("test")

        with pytest.raises(ValidationError, match="rejected"):
            novate_trade(
                tx_conn, uuid.UUID(trade_id), trade_data, trace,
            )

    def test_novate_cancelled_trade_rejected(self, tx_conn):
        """Cannot novate a trade that has been cancelled."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(tx_conn, buyer, seller, inst)

        tx_conn.execute(
            "UPDATE trades SET status = 'cancelled' WHERE id = %s",
            (trade_id,),
        )

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }
        trace = TraceContext.new_system("test")

        with pytest.raises(ValidationError, match="cancelled"):
            novate_trade(
                tx_conn, uuid.UUID(trade_id), trade_data, trace,
            )

    def test_novate_nonexistent_trade_rejected(self, tx_conn):
        """Cannot novate a trade that does not exist."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trace = TraceContext.new_system("test")

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        with pytest.raises(ValidationError, match="not found"):
            novate_trade(
                tx_conn, uuid.uuid4(), trade_data, trace,
            )


class TestIdempotency:
    """Test idempotent behavior for trade submission and novation."""

    def test_duplicate_external_trade_id_rejected(self, tx_conn):
        """UNIQUE constraint prevents duplicate external_trade_id."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)

        ext_id = f"EXT-DUPE-{uuid.uuid4().hex[:8]}"
        tx_conn.execute(
            """
            INSERT INTO trades
                (id, external_trade_id, instrument_id,
                 buyer_member_id, seller_member_id,
                 quantity, price, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted')
            """,
            (
                str(uuid.uuid4()), ext_id, inst,
                buyer, seller,
                Decimal("100"), Decimal("50"),
            ),
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            tx_conn.execute(
                """
                INSERT INTO trades
                    (id, external_trade_id, instrument_id,
                     buyer_member_id, seller_member_id,
                     quantity, price, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted')
                """,
                (
                    str(uuid.uuid4()), ext_id, inst,
                    buyer, seller,
                    Decimal("50"), Decimal("100"),
                ),
            )

    def test_double_novation_blocked(self, tx_conn):
        """Re-novating the same trade does not create duplicate legs."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(tx_conn, buyer, seller, inst)
        trace = TraceContext.new_system("test")

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        novate_trade(tx_conn, uuid.UUID(trade_id), trade_data, trace)

        with pytest.raises(ValidationError):
            novate_trade(
                tx_conn, uuid.UUID(trade_id), trade_data, trace,
            )

        count = tx_conn.execute(
            """
            SELECT COUNT(*) FROM novated_trades
            WHERE original_trade_id = %s
            """,
            (trade_id,),
        ).fetchone()[0]
        assert count == 2

    def test_outbox_not_duplicated_on_retry(self, tx_conn):
        """Failed re-novation does not emit a duplicate outbox event."""
        buyer = _insert_member(tx_conn)
        seller = _insert_member(tx_conn)
        inst = _insert_instrument(tx_conn)
        trade_id = _insert_trade(tx_conn, buyer, seller, inst)
        trace = TraceContext.new_system("test")

        trade_data = {
            "buyer_member_id": buyer,
            "seller_member_id": seller,
            "instrument_id": inst,
            "quantity": Decimal("100"),
            "price": Decimal("50"),
        }

        novate_trade(tx_conn, uuid.UUID(trade_id), trade_data, trace)

        with pytest.raises(ValidationError):
            novate_trade(
                tx_conn, uuid.UUID(trade_id), trade_data, trace,
            )

        event_count = tx_conn.execute(
            """
            SELECT COUNT(*) FROM outbox_events
            WHERE aggregate_id = %s
              AND event_type = 'trade.novated'
            """,
            (trade_id,),
        ).fetchone()[0]
        assert event_count == 1
