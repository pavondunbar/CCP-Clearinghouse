"""Create trades, novated_trades tables and member_positions view

Revision ID: 005
Revises: 004
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE trades (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            external_trade_id VARCHAR(100) UNIQUE NOT NULL,
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            buyer_member_id UUID NOT NULL REFERENCES members(id),
            seller_member_id UUID NOT NULL REFERENCES members(id),
            quantity NUMERIC(28, 8) NOT NULL,
            price NUMERIC(28, 8) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'submitted',
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_trades_status
                CHECK (status IN (
                    'submitted', 'validated', 'novated',
                    'rejected', 'cancelled'
                ))
        )
    """)

    op.execute("""
        CREATE TABLE novated_trades (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            original_trade_id UUID NOT NULL REFERENCES trades(id),
            member_id UUID NOT NULL REFERENCES members(id),
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            side VARCHAR(4) NOT NULL,
            quantity NUMERIC(28, 8) NOT NULL,
            price NUMERIC(28, 8) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            novated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT chk_novated_trades_side
                CHECK (side IN ('BUY', 'SELL')),
            CONSTRAINT chk_novated_trades_status
                CHECK (status IN ('open', 'closed', 'defaulted'))
        )
    """)

    op.execute("""
        CREATE VIEW member_positions AS
        SELECT
            member_id,
            instrument_id,
            SUM(CASE WHEN side = 'BUY' THEN quantity ELSE 0 END)
                AS long_quantity,
            SUM(CASE WHEN side = 'SELL' THEN quantity ELSE 0 END)
                AS short_quantity,
            SUM(CASE WHEN side = 'BUY' THEN quantity
                ELSE -quantity END)
                AS net_quantity,
            SUM(quantity * price) / NULLIF(SUM(quantity), 0)
                AS avg_price
        FROM novated_trades
        WHERE status = 'open'
        GROUP BY member_id, instrument_id
    """)

    op.execute("GRANT SELECT ON trades TO readonly_user")
    op.execute("GRANT SELECT ON novated_trades TO readonly_user")
    op.execute("GRANT SELECT ON member_positions TO readonly_user")

    op.execute("GRANT SELECT ON trades TO ledger_user")
    op.execute("GRANT SELECT ON novated_trades TO ledger_user")
    op.execute("GRANT SELECT ON member_positions TO ledger_user")


def downgrade():
    op.execute("DROP VIEW IF EXISTS member_positions")
    op.execute("DROP TABLE IF EXISTS novated_trades")
    op.execute("DROP TABLE IF EXISTS trades")
