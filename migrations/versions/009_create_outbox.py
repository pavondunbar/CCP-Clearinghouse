"""Create outbox_events table

Revision ID: 009
Revises: 008
"""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE outbox_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            aggregate_type VARCHAR(50) NOT NULL,
            aggregate_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            topic VARCHAR(100) NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE INDEX idx_outbox_unpublished
            ON outbox_events (created_at)
            WHERE published_at IS NULL
    """)

    op.execute("GRANT SELECT ON outbox_events TO readonly_user")
    op.execute(
        "GRANT SELECT, INSERT ON outbox_events TO ledger_user"
    )
    op.execute("""
        GRANT UPDATE (published_at) ON outbox_events TO ledger_user
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_outbox_unpublished")
    op.execute("DROP TABLE IF EXISTS outbox_events")
