"""Fix constraint mismatches between DB and application enums

Two constraints were out of sync with the application domain model:

1. settlement_instructions.chk_settlement_type allowed
   ('cash', 'physical', 'hybrid', 'on_chain') but SettlementType enum
   and instruments table use ('cash', 'physical', 'dvp').

2. novated_trades.chk_novated_trades_status allowed
   ('open', 'closed', 'defaulted') but NovatedTradeStatus enum uses
   ('open', 'netted', 'settled', 'defaulted').

Revision ID: 022
Revises: 021
"""
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE settlement_instructions "
        "DROP CONSTRAINT chk_settlement_type"
    )
    op.execute("""
        ALTER TABLE settlement_instructions
        ADD CONSTRAINT chk_settlement_type
            CHECK (settlement_type IN ('cash', 'physical', 'dvp'))
    """)

    op.execute(
        "ALTER TABLE novated_trades "
        "DROP CONSTRAINT chk_novated_trades_status"
    )
    op.execute("""
        ALTER TABLE novated_trades
        ADD CONSTRAINT chk_novated_trades_status
            CHECK (status IN (
                'open', 'netted', 'settled', 'defaulted'
            ))
    """)


def downgrade():
    op.execute(
        "ALTER TABLE settlement_instructions "
        "DROP CONSTRAINT chk_settlement_type"
    )
    op.execute("""
        ALTER TABLE settlement_instructions
        ADD CONSTRAINT chk_settlement_type
            CHECK (settlement_type IN (
                'cash', 'physical', 'hybrid', 'on_chain'
            ))
    """)

    op.execute(
        "ALTER TABLE novated_trades "
        "DROP CONSTRAINT chk_novated_trades_status"
    )
    op.execute("""
        ALTER TABLE novated_trades
        ADD CONSTRAINT chk_novated_trades_status
            CHECK (status IN ('open', 'closed', 'defaulted'))
    """)
