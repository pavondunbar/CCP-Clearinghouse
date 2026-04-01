"""Add reference_id to processed_events, immutability trigger on state_transitions

Revision ID: 021
Revises: 020
"""
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE processed_events
        ADD COLUMN reference_id UUID
    """)

    op.execute("""
        CREATE TRIGGER trg_state_transitions_immutable
            BEFORE UPDATE OR DELETE ON state_transitions
            FOR EACH ROW EXECUTE FUNCTION prevent_mutation()
    """)


def downgrade():
    op.execute(
        "DROP TRIGGER IF EXISTS trg_state_transitions_immutable "
        "ON state_transitions"
    )
    op.execute("""
        ALTER TABLE processed_events
        DROP COLUMN IF EXISTS reference_id
    """)
