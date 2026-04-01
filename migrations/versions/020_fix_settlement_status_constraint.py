"""Fix settlement_instructions status constraint for full state machine

Revision ID: 020
Revises: 019
"""
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE settlement_instructions "
        "DROP CONSTRAINT chk_settlement_status"
    )
    op.execute("""
        ALTER TABLE settlement_instructions
        ADD CONSTRAINT chk_settlement_status
            CHECK (status IN (
                'pending', 'approved', 'signed', 'broadcasted',
                'confirmed', 'failed', 'cancelled'
            ))
    """)

    op.execute(
        "GRANT UPDATE ON settlement_instructions TO ledger_user"
    )


def downgrade():
    op.execute(
        "ALTER TABLE settlement_instructions "
        "DROP CONSTRAINT chk_settlement_status"
    )
    op.execute("""
        ALTER TABLE settlement_instructions
        ADD CONSTRAINT chk_settlement_status
            CHECK (status IN (
                'pending', 'submitted', 'confirmed',
                'failed', 'cancelled'
            ))
    """)
