"""Add trace_id and actor columns for audit trails

Revision ID: 018
Revises: 017
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE state_transitions ADD COLUMN trace_id UUID"
    )
    op.execute(
        "ALTER TABLE state_transitions "
        "ADD COLUMN actor VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE outbox_events ADD COLUMN trace_id UUID"
    )

    op.execute(
        "CREATE INDEX idx_state_transitions_trace_id "
        "ON state_transitions (trace_id) "
        "WHERE trace_id IS NOT NULL"
    )


def downgrade():
    op.execute(
        "DROP INDEX IF EXISTS idx_state_transitions_trace_id"
    )
    op.execute(
        "ALTER TABLE outbox_events DROP COLUMN IF EXISTS trace_id"
    )
    op.execute(
        "ALTER TABLE state_transitions "
        "DROP COLUMN IF EXISTS actor"
    )
    op.execute(
        "ALTER TABLE state_transitions "
        "DROP COLUMN IF EXISTS trace_id"
    )
