"""Create default_events and waterfall_steps tables

Revision ID: 012
Revises: 011
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE default_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            member_id UUID NOT NULL REFERENCES members(id),
            trigger_reason TEXT NOT NULL,
            total_exposure NUMERIC(28, 8) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'detected',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,
            CONSTRAINT chk_default_event_status
                CHECK (status IN (
                    'detected', 'margin_applied',
                    'default_fund_applied', 'ccp_skin_applied',
                    'assessment_applied', 'resolved', 'escalated'
                ))
        )
    """)

    op.execute("""
        CREATE TABLE waterfall_steps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            default_event_id UUID NOT NULL
                REFERENCES default_events(id),
            step_order INT NOT NULL,
            step_type VARCHAR(40) NOT NULL,
            available_amount NUMERIC(28, 8) NOT NULL DEFAULT 0,
            applied_amount NUMERIC(28, 8) NOT NULL DEFAULT 0,
            remaining_loss NUMERIC(28, 8) NOT NULL DEFAULT 0,
            journal_id UUID REFERENCES journals(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_waterfall_step_type
                CHECK (step_type IN (
                    'DEFAULTER_MARGIN',
                    'DEFAULTER_DEFAULT_FUND',
                    'CCP_FIRST_TRANCHE',
                    'SURVIVOR_DEFAULT_FUND',
                    'CCP_SECOND_TRANCHE',
                    'ASSESSMENT_POWERS'
                ))
        )
    """)

    op.execute("GRANT SELECT ON default_events TO readonly_user")
    op.execute(
        "GRANT SELECT ON waterfall_steps TO readonly_user"
    )

    op.execute(
        "GRANT SELECT, INSERT ON default_events TO ledger_user"
    )
    op.execute(
        "GRANT SELECT, INSERT ON waterfall_steps TO ledger_user"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS waterfall_steps")
    op.execute("DROP TABLE IF EXISTS default_events")
