"""Create members table

Revision ID: 002
Revises: 001
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lei VARCHAR(20) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            credit_limit NUMERIC(28, 8) NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_members_status
                CHECK (status IN ('pending', 'active', 'suspended', 'defaulted'))
        )
    """)

    op.execute("GRANT SELECT ON members TO readonly_user")
    op.execute("GRANT SELECT ON members TO ledger_user")


def downgrade():
    op.execute("DROP TABLE IF EXISTS members")
