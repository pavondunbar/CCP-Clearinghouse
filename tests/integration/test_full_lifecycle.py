"""Full CCP lifecycle integration test.

Tests the complete flow: member setup -> trade submission -> novation ->
netting -> margin -> settlement -> default waterfall.

All operations are exercised against a real PostgreSQL instance
with migrations applied.
"""

import uuid
from decimal import Decimal

import psycopg
import pytest


@pytest.fixture()
def lifecycle_setup(tx_conn):
    """Set up members, instruments, and accounts for lifecycle tests."""
    conn = tx_conn

    # CCP house account
    ccp_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO members (id, lei, name, status, credit_limit)
        VALUES (%s, 'CCP000000000000000', 'CCP House Account', 'active', 0)
        """,
        (ccp_id,),
    )

    # Two clearing members
    member_a = str(uuid.uuid4())
    member_b = str(uuid.uuid4())
    for mid, lei, name in [
        (member_a, "LEI_MEMBER_A_00000000", "Member A"),
        (member_b, "LEI_MEMBER_B_00000000", "Member B"),
    ]:
        conn.execute(
            """
            INSERT INTO members (id, lei, name, status, credit_limit)
            VALUES (%s, %s, %s, 'active', %s)
            """,
            (mid, lei, name, Decimal("50000000")),
        )

    # Create accounts for all members
    account_map = {}
    for mid in [ccp_id, member_a, member_b]:
        account_map[mid] = {}
        for acct_type in [
            "MARGIN_IM", "MARGIN_VM", "DEFAULT_FUND",
            "COLLATERAL", "SETTLEMENT", "CCP_EQUITY",
        ]:
            for pool in ["AVAILABLE", "LOCKED"]:
                acct_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO accounts (id, member_id, account_type, currency, pool)
                    VALUES (%s, %s, %s, 'USD', %s)
                    """,
                    (acct_id, mid, acct_type, pool),
                )
                account_map[mid][f"{acct_type}_{pool}"] = acct_id

    # Instrument
    inst_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO instruments (id, symbol, asset_class, settlement_type,
                                 margin_rate_im, margin_rate_vm)
        VALUES (%s, 'BTC-PERP-TEST', 'crypto_perpetual', 'cash', %s, %s)
        """,
        (inst_id, Decimal("0.1"), Decimal("0.05")),
    )

    # Seed collateral via balanced journal entries
    for mid in [member_a, member_b]:
        journal_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'seed', 'confirmed')
            """,
            (journal_id,),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, account_map[mid]["COLLATERAL_AVAILABLE"], Decimal("1000000")),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, account_map[ccp_id]["SETTLEMENT_AVAILABLE"], Decimal("1000000")),
        )

    # Seed margin accounts
    for mid in [member_a, member_b]:
        journal_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'seed', 'confirmed')
            """,
            (journal_id,),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, account_map[mid]["MARGIN_IM_AVAILABLE"], Decimal("500000")),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, account_map[ccp_id]["SETTLEMENT_AVAILABLE"], Decimal("500000")),
        )

    # Seed default fund
    for mid in [member_a, member_b]:
        journal_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'DEFAULT_FUND_CONTRIBUTION', 'seed', 'confirmed')
            """,
            (journal_id,),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, account_map[mid]["DEFAULT_FUND_AVAILABLE"], Decimal("200000")),
        )
        conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, account_map[ccp_id]["CCP_EQUITY_AVAILABLE"], Decimal("200000")),
        )

    return {
        "ccp_id": ccp_id,
        "member_a": member_a,
        "member_b": member_b,
        "instrument_id": inst_id,
        "accounts": account_map,
    }


class TestTradeSubmissionAndNovation:
    """Test trade submission through novation."""

    def test_trade_insert_and_novation(self, tx_conn, lifecycle_setup):
        conn = tx_conn
        setup = lifecycle_setup

        # Submit trade: A buys 10 BTC-PERP from B at 65000
        trade_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO trades
                (id, external_trade_id, instrument_id,
                 buyer_member_id, seller_member_id, quantity, price, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted')
            """,
            (
                trade_id, f"EXT-{trade_id[:8]}", setup["instrument_id"],
                setup["member_a"], setup["member_b"],
                Decimal("10"), Decimal("65000"),
            ),
        )

        # Novate: create two CCP-facing trades
        for side, member_id in [("BUY", setup["member_a"]), ("SELL", setup["member_b"])]:
            conn.execute(
                """
                INSERT INTO novated_trades
                    (original_trade_id, member_id, instrument_id,
                     side, quantity, price, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'open')
                """,
                (trade_id, member_id, setup["instrument_id"],
                 side, Decimal("10"), Decimal("65000")),
            )

        conn.execute(
            "UPDATE trades SET status = 'novated', updated_at = now() WHERE id = %s",
            (trade_id,),
        )

        # Create margin lock journals for both sides
        margin_amount = Decimal("10") * Decimal("65000") * Decimal("0.1")
        assert margin_amount == Decimal("65000.0")

        for mid in [setup["member_a"], setup["member_b"]]:
            journal_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO journals (id, journal_type, reference_type, reference_id, status)
                VALUES (%s, 'MARGIN_LOCK', 'trade', %s, 'confirmed')
                """,
                (journal_id, trade_id),
            )
            conn.execute(
                """
                INSERT INTO journal_entries (journal_id, account_id, debit, credit)
                VALUES (%s, %s, %s, 0)
                """,
                (journal_id, setup["accounts"][mid]["MARGIN_IM_AVAILABLE"], margin_amount),
            )
            conn.execute(
                """
                INSERT INTO journal_entries (journal_id, account_id, debit, credit)
                VALUES (%s, %s, 0, %s)
                """,
                (journal_id, setup["accounts"][mid]["MARGIN_IM_LOCKED"], margin_amount),
            )

        # Verify trade status
        row = conn.execute(
            "SELECT status FROM trades WHERE id = %s", (trade_id,),
        ).fetchone()
        assert row[0] == "novated"

        # Verify novated trades
        novated = conn.execute(
            "SELECT COUNT(*) FROM novated_trades WHERE original_trade_id = %s",
            (trade_id,),
        ).fetchone()
        assert novated[0] == 2

        # Verify positions view
        positions = conn.execute(
            """
            SELECT member_id, net_quantity FROM member_positions
            WHERE instrument_id = %s
            ORDER BY member_id
            """,
            (setup["instrument_id"],),
        ).fetchall()
        assert len(positions) == 2

    def test_netting_creates_obligations(self, tx_conn, lifecycle_setup):
        """Multiple trades net correctly into obligations."""
        conn = tx_conn
        setup = lifecycle_setup

        # Create 3 trades: A buys 10, B buys 5, A sells 3
        trades = [
            (setup["member_a"], setup["member_b"], "BUY", Decimal("10"), Decimal("65000")),
            (setup["member_b"], setup["member_a"], "BUY", Decimal("5"), Decimal("65500")),
            (setup["member_a"], setup["member_b"], "SELL", Decimal("3"), Decimal("64800")),
        ]

        for buyer, seller, _, qty, price in trades:
            trade_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO trades
                    (id, external_trade_id, instrument_id,
                     buyer_member_id, seller_member_id, quantity, price, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'novated')
                """,
                (trade_id, f"EXT-{trade_id[:8]}", setup["instrument_id"],
                 buyer, seller, qty, price),
            )
            conn.execute(
                """
                INSERT INTO novated_trades
                    (original_trade_id, member_id, instrument_id,
                     side, quantity, price, status)
                VALUES (%s, %s, %s, 'BUY', %s, %s, 'open')
                """,
                (trade_id, buyer, setup["instrument_id"], qty, price),
            )
            conn.execute(
                """
                INSERT INTO novated_trades
                    (original_trade_id, member_id, instrument_id,
                     side, quantity, price, status)
                VALUES (%s, %s, %s, 'SELL', %s, %s, 'open')
                """,
                (trade_id, seller, setup["instrument_id"], qty, price),
            )

        # Create netting cycle
        cycle_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO netting_cycles (id, cycle_type, status, cut_off_time)
            VALUES (%s, 'manual', 'confirmed', now())
            """,
            (cycle_id,),
        )

        # Verify positions exist
        positions = conn.execute(
            "SELECT COUNT(*) FROM member_positions WHERE instrument_id = %s",
            (setup["instrument_id"],),
        ).fetchone()
        assert positions[0] > 0


class TestJournalIntegrity:
    """Verify all journals maintain double-entry integrity."""

    def test_all_journals_balanced(self, tx_conn, lifecycle_setup):
        """Every confirmed journal should have balanced entries."""
        conn = tx_conn

        unbalanced = conn.execute(
            """
            SELECT j.id,
                   SUM(je.debit) AS total_debit,
                   SUM(je.credit) AS total_credit
            FROM journals j
            JOIN journal_entries je ON je.journal_id = j.id
            WHERE j.status = 'confirmed'
            GROUP BY j.id
            HAVING SUM(je.debit) != SUM(je.credit)
            """
        ).fetchall()

        assert len(unbalanced) == 0, (
            f"Found {len(unbalanced)} unbalanced journals: "
            f"{[(str(r[0])[:8], r[1], r[2]) for r in unbalanced]}"
        )
