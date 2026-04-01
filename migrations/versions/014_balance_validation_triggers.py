"""Create balance validation constraint trigger

Revision ID: 014
Revises: 013
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_journal_balance()
        RETURNS TRIGGER AS $$
        DECLARE
            total_debit NUMERIC(28, 8);
            total_credit NUMERIC(28, 8);
        BEGIN
            SELECT COALESCE(SUM(debit), 0),
                   COALESCE(SUM(credit), 0)
            INTO total_debit, total_credit
            FROM journal_entries
            WHERE journal_id = NEW.journal_id;

            IF total_debit <> total_credit THEN
                RAISE EXCEPTION
                    'Journal % is unbalanced: debits=% credits=%',
                    NEW.journal_id, total_debit, total_credit;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_validate_journal_balance
            AFTER INSERT ON journal_entries
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION validate_journal_balance()
    """)


def downgrade():
    op.execute(
        "DROP TRIGGER IF EXISTS trg_validate_journal_balance "
        "ON journal_entries"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS validate_journal_balance()"
    )
