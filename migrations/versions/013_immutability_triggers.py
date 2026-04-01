"""Create immutability triggers for ledger tables

Revision ID: 013
Revises: 012
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'Mutations not allowed on immutable table %',
                TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER trg_journal_entries_immutable
            BEFORE UPDATE OR DELETE ON journal_entries
            FOR EACH ROW EXECUTE FUNCTION prevent_mutation()
    """)

    op.execute("""
        CREATE TRIGGER trg_journals_immutable
            BEFORE UPDATE OR DELETE ON journals
            FOR EACH ROW EXECUTE FUNCTION prevent_mutation()
    """)


def downgrade():
    op.execute(
        "DROP TRIGGER IF EXISTS trg_journals_immutable ON journals"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_journal_entries_immutable "
        "ON journal_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_mutation()")
