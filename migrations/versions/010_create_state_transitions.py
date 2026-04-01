"""Create state_transitions table and current_entity_status view

Revision ID: 010
Revises: 009
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE state_transitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type VARCHAR(50) NOT NULL,
            entity_id UUID NOT NULL,
            from_status VARCHAR(30),
            to_status VARCHAR(30) NOT NULL,
            reason TEXT,
            transitioned_by VARCHAR(100),
            transitioned_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE VIEW current_entity_status AS
        SELECT DISTINCT ON (entity_type, entity_id)
            entity_type,
            entity_id,
            to_status AS current_status,
            transitioned_at
        FROM state_transitions
        ORDER BY entity_type, entity_id, transitioned_at DESC
    """)

    op.execute(
        "GRANT SELECT ON state_transitions TO readonly_user"
    )
    op.execute(
        "GRANT SELECT ON current_entity_status TO readonly_user"
    )

    op.execute(
        "GRANT SELECT, INSERT ON state_transitions TO ledger_user"
    )
    op.execute(
        "GRANT SELECT ON current_entity_status TO ledger_user"
    )


def downgrade():
    op.execute("DROP VIEW IF EXISTS current_entity_status")
    op.execute("DROP TABLE IF EXISTS state_transitions")
