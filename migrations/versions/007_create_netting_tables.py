"""Create netting_cycles and net_obligations tables

Revision ID: 007
Revises: 006
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE netting_cycles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cycle_type VARCHAR(20) NOT NULL DEFAULT 'scheduled',
            status VARCHAR(20) NOT NULL DEFAULT 'initiated',
            cut_off_time TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            CONSTRAINT chk_netting_cycle_type
                CHECK (cycle_type IN ('scheduled', 'ad_hoc')),
            CONSTRAINT chk_netting_cycle_status
                CHECK (status IN (
                    'initiated', 'calculating', 'confirmed',
                    'settled', 'failed'
                ))
        )
    """)

    op.execute("""
        CREATE TABLE net_obligations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            netting_cycle_id UUID NOT NULL
                REFERENCES netting_cycles(id),
            member_id UUID NOT NULL REFERENCES members(id),
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            net_quantity NUMERIC(28, 8) NOT NULL,
            net_amount NUMERIC(28, 8) NOT NULL,
            settlement_amount NUMERIC(28, 8) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("GRANT SELECT ON netting_cycles TO readonly_user")
    op.execute("GRANT SELECT ON net_obligations TO readonly_user")

    op.execute("GRANT SELECT ON netting_cycles TO ledger_user")
    op.execute("GRANT SELECT ON net_obligations TO ledger_user")


def downgrade():
    op.execute("DROP TABLE IF EXISTS net_obligations")
    op.execute("DROP TABLE IF EXISTS netting_cycles")
