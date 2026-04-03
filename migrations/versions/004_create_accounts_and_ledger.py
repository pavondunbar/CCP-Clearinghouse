"""Create accounts, journals, and journal_entries tables

Revision ID: 004
Revises: 003
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            member_id UUID NOT NULL REFERENCES members(id),
            account_type VARCHAR(30) NOT NULL,
            currency VARCHAR(10) NOT NULL DEFAULT 'USD',
            pool VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (member_id, account_type, currency, pool),
            CONSTRAINT chk_accounts_type
                CHECK (account_type IN (
                    'MARGIN_IM', 'MARGIN_VM', 'SETTLEMENT',
                    'DEFAULT_FUND', 'COLLATERAL', 'CCP_EQUITY'
                )),
            CONSTRAINT chk_accounts_pool
                CHECK (pool IN ('AVAILABLE', 'RESERVED', 'LOCKED'))
        )
    """)

    op.execute("""
        CREATE TABLE journals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            journal_type VARCHAR(40) NOT NULL,
            reference_type VARCHAR(50),
            reference_id UUID,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_journals_type
                CHECK (journal_type IN (
                    'MARGIN_DEPOSIT', 'MARGIN_WITHDRAWAL',
                    'MARGIN_CALL', 'SETTLEMENT',
                    'FEE_COLLECTION', 'DEFAULT_CLOSE_OUT',
                    'WATERFALL_LOSS', 'COLLATERAL_TRANSFER',
                    'NETTING', 'ADJUSTMENT',
                    'DEFAULT_FUND_CONTRIBUTION'
                )),
            CONSTRAINT chk_journals_status
                CHECK (status IN ('pending', 'confirmed', 'rejected'))
        )
    """)

    op.execute("""
        CREATE TABLE journal_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            journal_id UUID NOT NULL REFERENCES journals(id),
            account_id UUID NOT NULL REFERENCES accounts(id),
            debit NUMERIC(28, 8) NOT NULL DEFAULT 0,
            credit NUMERIC(28, 8) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (debit >= 0 AND credit >= 0),
            CHECK ((debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0))
        )
    """)

    op.execute("GRANT SELECT ON accounts TO readonly_user")
    op.execute("GRANT SELECT ON journals TO readonly_user")
    op.execute("GRANT SELECT ON journal_entries TO readonly_user")

    op.execute(
        "GRANT SELECT, INSERT ON accounts TO ledger_user"
    )
    op.execute(
        "GRANT SELECT, INSERT ON journals TO ledger_user"
    )
    op.execute(
        "GRANT SELECT, INSERT ON journal_entries TO ledger_user"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS journal_entries")
    op.execute("DROP TABLE IF EXISTS journals")
    op.execute("DROP TABLE IF EXISTS accounts")
