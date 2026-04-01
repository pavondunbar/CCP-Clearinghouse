"""Create margin_requirements and margin_calls tables

Revision ID: 006
Revises: 005
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE margin_requirements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            member_id UUID NOT NULL REFERENCES members(id),
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            margin_type VARCHAR(20) NOT NULL,
            required_amount NUMERIC(28, 8) NOT NULL DEFAULT 0,
            posted_amount NUMERIC(28, 8) NOT NULL DEFAULT 0,
            shortfall NUMERIC(28, 8) GENERATED ALWAYS AS (
                GREATEST(required_amount - posted_amount, 0)
            ) STORED,
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (member_id, instrument_id, margin_type),
            CONSTRAINT chk_margin_type
                CHECK (margin_type IN ('INITIAL', 'VARIATION'))
        )
    """)

    op.execute("""
        CREATE TABLE margin_calls (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            member_id UUID NOT NULL REFERENCES members(id),
            margin_requirement_id UUID
                REFERENCES margin_requirements(id),
            call_amount NUMERIC(28, 8) NOT NULL,
            deadline TIMESTAMPTZ NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'issued',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_margin_calls_status
                CHECK (status IN (
                    'issued', 'acknowledged', 'met',
                    'partially_met', 'breached'
                ))
        )
    """)

    op.execute("GRANT SELECT ON margin_requirements TO readonly_user")
    op.execute("GRANT SELECT ON margin_calls TO readonly_user")

    op.execute(
        "GRANT SELECT, INSERT ON margin_requirements TO ledger_user"
    )
    op.execute(
        "GRANT SELECT, INSERT ON margin_calls TO ledger_user"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS margin_calls")
    op.execute("DROP TABLE IF EXISTS margin_requirements")
