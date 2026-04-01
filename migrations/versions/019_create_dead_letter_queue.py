"""Create dead_letter_events table for DLQ

Revision ID: 019
Revises: 018
"""
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE dead_letter_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            service_name VARCHAR(100) NOT NULL,
            topic VARCHAR(100) NOT NULL,
            event_key VARCHAR(255),
            payload JSONB NOT NULL,
            error_message TEXT NOT NULL,
            error_traceback TEXT,
            original_timestamp TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            retried_at TIMESTAMPTZ,
            retry_count INT NOT NULL DEFAULT 0
        )
    """)

    op.execute(
        "CREATE INDEX idx_dlq_service_name "
        "ON dead_letter_events (service_name)"
    )
    op.execute(
        "CREATE INDEX idx_dlq_created_at "
        "ON dead_letter_events (created_at DESC)"
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE "
        "ON dead_letter_events TO ledger_user"
    )
    op.execute(
        "GRANT SELECT ON dead_letter_events TO readonly_user"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_dlq_created_at")
    op.execute("DROP INDEX IF EXISTS idx_dlq_service_name")
    op.execute("DROP TABLE IF EXISTS dead_letter_events")
