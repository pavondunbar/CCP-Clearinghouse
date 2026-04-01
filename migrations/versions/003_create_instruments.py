"""Create instruments table

Revision ID: 003
Revises: 002
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE instruments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol VARCHAR(50) UNIQUE NOT NULL,
            asset_class VARCHAR(30) NOT NULL,
            settlement_type VARCHAR(20) NOT NULL DEFAULT 'cash',
            margin_rate_im NUMERIC(10, 6) NOT NULL,
            margin_rate_vm NUMERIC(10, 6) NOT NULL,
            chain_id VARCHAR(50),
            contract_address VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_instruments_asset_class
                CHECK (asset_class IN (
                    'equity', 'fixed_income', 'commodity',
                    'fx', 'crypto', 'derivative'
                )),
            CONSTRAINT chk_instruments_settlement_type
                CHECK (settlement_type IN ('cash', 'physical', 'hybrid'))
        )
    """)

    op.execute("GRANT SELECT ON instruments TO readonly_user")
    op.execute("GRANT SELECT ON instruments TO ledger_user")


def downgrade():
    op.execute("DROP TABLE IF EXISTS instruments")
