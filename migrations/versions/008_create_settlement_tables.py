"""Create settlement_instructions table

Revision ID: 008
Revises: 007
"""
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE settlement_instructions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            settlement_type VARCHAR(20) NOT NULL,
            netting_cycle_id UUID REFERENCES netting_cycles(id),
            from_member_id UUID NOT NULL REFERENCES members(id),
            to_member_id UUID NOT NULL REFERENCES members(id),
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            quantity NUMERIC(28, 8) NOT NULL DEFAULT 0,
            amount NUMERIC(28, 8) NOT NULL DEFAULT 0,
            chain_id VARCHAR(50),
            tx_hash VARCHAR(255),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            block_number BIGINT,
            confirmations INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_settlement_type
                CHECK (settlement_type IN (
                    'cash', 'physical', 'hybrid', 'on_chain'
                )),
            CONSTRAINT chk_settlement_status
                CHECK (status IN (
                    'pending', 'submitted', 'confirmed',
                    'failed', 'cancelled'
                ))
        )
    """)

    op.execute(
        "GRANT SELECT ON settlement_instructions TO readonly_user"
    )
    op.execute(
        "GRANT SELECT ON settlement_instructions TO ledger_user"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS settlement_instructions")
