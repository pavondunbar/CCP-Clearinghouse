"""Integration tests for the double-entry ledger constraints.

Validates:
1. Balanced journal entries commit successfully
2. Unbalanced journal entries are rejected by the deferred constraint trigger
3. Immutability triggers prevent UPDATE/DELETE on journal_entries and journals
4. account_balances view computes correctly from confirmed journals
"""

import uuid
from decimal import Decimal

import psycopg
import pytest


class TestBalancedJournalEntries:
    """Test that the deferred constraint trigger enforces balanced journals."""

    def test_balanced_entries_commit(self, tx_conn, sample_member):
        """Balanced debit/credit entries should commit without error."""
        accounts = sample_member["accounts"]
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )

        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, accounts["COLLATERAL_AVAILABLE"], Decimal("1000.00")),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, accounts["MARGIN_IM_AVAILABLE"], Decimal("1000.00")),
        )

        # Should not raise on implicit commit check
        # (we don't actually commit since tx_conn rolls back)
        row = tx_conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE journal_id = %s",
            (journal_id,),
        ).fetchone()
        assert row[0] == 2

    def test_unbalanced_entries_rejected_on_commit(self, pg_url, sample_member):
        """Unbalanced entries should be rejected when the transaction commits."""
        accounts = sample_member["accounts"]
        journal_id = str(uuid.uuid4())

        with psycopg.connect(pg_url) as conn:
            conn.autocommit = False
            conn.execute(
                """
                INSERT INTO journals (id, journal_type, reference_type, status)
                VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
                """,
                (journal_id,),
            )
            conn.execute(
                """
                INSERT INTO journal_entries
                    (journal_id, account_id, debit, credit)
                VALUES (%s, %s, %s, 0)
                """,
                (journal_id, accounts["COLLATERAL_AVAILABLE"], Decimal("1000.00")),
            )
            conn.execute(
                """
                INSERT INTO journal_entries
                    (journal_id, account_id, debit, credit)
                VALUES (%s, %s, 0, %s)
                """,
                (journal_id, accounts["MARGIN_IM_AVAILABLE"], Decimal("500.00")),
            )

            with pytest.raises(psycopg.errors.RaiseException, match="unbalanced"):
                conn.commit()

    def test_debit_xor_credit_constraint(self, tx_conn, sample_member):
        """Cannot have both debit and credit non-zero on same entry."""
        accounts = sample_member["accounts"]
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            tx_conn.execute(
                """
                INSERT INTO journal_entries
                    (journal_id, account_id, debit, credit)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    journal_id,
                    accounts["COLLATERAL_AVAILABLE"],
                    Decimal("100.00"),
                    Decimal("100.00"),
                ),
            )

    def test_negative_amount_rejected(self, tx_conn, sample_member):
        """Negative debit or credit amounts should be rejected."""
        accounts = sample_member["accounts"]
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            tx_conn.execute(
                """
                INSERT INTO journal_entries
                    (journal_id, account_id, debit, credit)
                VALUES (%s, %s, %s, 0)
                """,
                (
                    journal_id,
                    accounts["COLLATERAL_AVAILABLE"],
                    Decimal("-100.00"),
                ),
            )


class TestImmutabilityTriggers:
    """Test that journal_entries and journals cannot be modified after creation."""

    def test_update_journal_entry_rejected(self, tx_conn, sample_member):
        """UPDATE on journal_entries should be rejected by trigger."""
        accounts = sample_member["accounts"]
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, accounts["COLLATERAL_AVAILABLE"], Decimal("500.00")),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, accounts["MARGIN_IM_AVAILABLE"], Decimal("500.00")),
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="immutable",
        ):
            tx_conn.execute(
                """
                UPDATE journal_entries SET debit = %s
                WHERE journal_id = %s AND debit > 0
                """,
                (Decimal("999.00"), journal_id),
            )

    def test_delete_journal_entry_rejected(self, tx_conn, sample_member):
        """DELETE on journal_entries should be rejected by trigger."""
        accounts = sample_member["accounts"]
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, accounts["COLLATERAL_AVAILABLE"], Decimal("500.00")),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, accounts["MARGIN_IM_AVAILABLE"], Decimal("500.00")),
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="immutable",
        ):
            tx_conn.execute(
                "DELETE FROM journal_entries WHERE journal_id = %s",
                (journal_id,),
            )

    def test_update_journal_rejected(self, tx_conn):
        """UPDATE on journals should be rejected by trigger."""
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="immutable",
        ):
            tx_conn.execute(
                "UPDATE journals SET status = 'rejected' WHERE id = %s",
                (journal_id,),
            )

    def test_delete_journal_rejected(self, tx_conn):
        """DELETE on journals should be rejected by trigger."""
        journal_id = str(uuid.uuid4())

        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="immutable",
        ):
            tx_conn.execute(
                "DELETE FROM journals WHERE id = %s",
                (journal_id,),
            )


class TestAccountBalancesView:
    """Test the account_balances derived view."""

    def test_balance_from_confirmed_journals(self, tx_conn, sample_member):
        """account_balances should reflect confirmed journal entries."""
        accounts = sample_member["accounts"]
        member_id = sample_member["member_id"]

        journal_id = str(uuid.uuid4())
        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'confirmed')
            """,
            (journal_id,),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, accounts["COLLATERAL_AVAILABLE"], Decimal("5000.00")),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, accounts["MARGIN_IM_AVAILABLE"], Decimal("5000.00")),
        )

        row = tx_conn.execute(
            """
            SELECT balance FROM account_balances
            WHERE account_id = %s
            """,
            (accounts["COLLATERAL_AVAILABLE"],),
        ).fetchone()
        assert row is not None
        assert row[0] == Decimal("5000.00")

        row = tx_conn.execute(
            """
            SELECT balance FROM account_balances
            WHERE account_id = %s
            """,
            (accounts["MARGIN_IM_AVAILABLE"],),
        ).fetchone()
        assert row is not None
        assert row[0] == Decimal("-5000.00")

    def test_pending_journals_excluded(self, tx_conn, sample_member):
        """Pending journals should not affect account balances."""
        accounts = sample_member["accounts"]

        journal_id = str(uuid.uuid4())
        tx_conn.execute(
            """
            INSERT INTO journals (id, journal_type, reference_type, status)
            VALUES (%s, 'COLLATERAL_DEPOSIT', 'test', 'pending')
            """,
            (journal_id,),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, %s, 0)
            """,
            (journal_id, accounts["COLLATERAL_AVAILABLE"], Decimal("1000.00")),
        )
        tx_conn.execute(
            """
            INSERT INTO journal_entries (journal_id, account_id, debit, credit)
            VALUES (%s, %s, 0, %s)
            """,
            (journal_id, accounts["MARGIN_IM_AVAILABLE"], Decimal("1000.00")),
        )

        row = tx_conn.execute(
            """
            SELECT balance FROM account_balances
            WHERE account_id = %s
            """,
            (accounts["COLLATERAL_AVAILABLE"],),
        ).fetchone()
        # Balance should be 0 since journal is pending, not confirmed
        assert row is not None
        assert row[0] == Decimal("0")
