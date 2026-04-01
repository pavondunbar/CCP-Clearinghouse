"""Create price_feeds table and latest_prices materialized view

Revision ID: 011
Revises: 010
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE price_feeds (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            price NUMERIC(28, 8) NOT NULL,
            source VARCHAR(50) NOT NULL DEFAULT 'mock',
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE MATERIALIZED VIEW latest_prices AS
        SELECT DISTINCT ON (instrument_id)
            instrument_id,
            price,
            source,
            received_at
        FROM price_feeds
        ORDER BY instrument_id, received_at DESC
    """)

    op.execute("""
        CREATE UNIQUE INDEX idx_latest_prices_instrument
            ON latest_prices (instrument_id)
    """)

    op.execute("GRANT SELECT ON price_feeds TO readonly_user")
    op.execute("GRANT SELECT ON latest_prices TO readonly_user")

    op.execute(
        "GRANT SELECT, INSERT ON price_feeds TO ledger_user"
    )
    op.execute("GRANT SELECT ON latest_prices TO ledger_user")


def downgrade():
    op.execute(
        "DROP INDEX IF EXISTS idx_latest_prices_instrument"
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS latest_prices")
    op.execute("DROP TABLE IF EXISTS price_feeds")
