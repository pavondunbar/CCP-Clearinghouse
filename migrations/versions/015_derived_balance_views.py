"""Create account_balances derived view

Revision ID: 015
Revises: 014
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE VIEW account_balances AS
        SELECT
            a.id AS account_id,
            a.member_id,
            a.account_type,
            a.currency,
            a.pool,
            COALESCE(
                SUM(je.debit) - SUM(je.credit), 0
            ) AS balance
        FROM accounts a
        LEFT JOIN journal_entries je
            ON je.account_id = a.id
        LEFT JOIN journals j
            ON j.id = je.journal_id
            AND j.status = 'confirmed'
        GROUP BY
            a.id, a.member_id, a.account_type,
            a.currency, a.pool
    """)

    op.execute(
        "GRANT SELECT ON account_balances TO readonly_user"
    )
    op.execute(
        "GRANT SELECT ON account_balances TO ledger_user"
    )


def downgrade():
    op.execute("DROP VIEW IF EXISTS account_balances")
