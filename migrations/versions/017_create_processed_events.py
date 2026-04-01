"""Create processed_events table for consumer idempotency

Revision ID: 017
Revises: 016
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE processed_events (
            service_name VARCHAR(100) NOT NULL,
            event_id UUID NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (service_name, event_id)
        )
    """)

    op.execute(
        "GRANT SELECT, INSERT ON processed_events TO ledger_user"
    )
    op.execute(
        "GRANT SELECT ON processed_events TO readonly_user"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS processed_events")
