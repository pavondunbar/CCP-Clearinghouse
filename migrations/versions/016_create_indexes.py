"""Create performance indexes

Revision ID: 016
Revises: 015
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

INDEXES = [
    ("idx_members_status", "members", "status"),
    ("idx_accounts_member_id", "accounts", "member_id"),
    ("idx_journal_entries_journal_id",
     "journal_entries", "journal_id"),
    ("idx_journal_entries_account_id",
     "journal_entries", "account_id"),
    ("idx_trades_instrument_id", "trades", "instrument_id"),
    ("idx_trades_buyer_member_id",
     "trades", "buyer_member_id"),
    ("idx_trades_seller_member_id",
     "trades", "seller_member_id"),
    ("idx_trades_status", "trades", "status"),
    ("idx_novated_trades_original_trade_id",
     "novated_trades", "original_trade_id"),
    ("idx_novated_trades_member_id",
     "novated_trades", "member_id"),
    ("idx_novated_trades_instrument_id",
     "novated_trades", "instrument_id"),
    ("idx_novated_trades_status",
     "novated_trades", "status"),
    ("idx_margin_calls_member_id",
     "margin_calls", "member_id"),
    ("idx_margin_calls_status", "margin_calls", "status"),
    ("idx_netting_cycles_status",
     "netting_cycles", "status"),
    ("idx_net_obligations_netting_cycle_id",
     "net_obligations", "netting_cycle_id"),
    ("idx_settlement_instructions_status",
     "settlement_instructions", "status"),
    ("idx_settlement_instructions_from_member_id",
     "settlement_instructions", "from_member_id"),
    ("idx_settlement_instructions_to_member_id",
     "settlement_instructions", "to_member_id"),
    ("idx_default_events_member_id",
     "default_events", "member_id"),
    ("idx_default_events_status",
     "default_events", "status"),
    ("idx_waterfall_steps_default_event_id",
     "waterfall_steps", "default_event_id"),
]

COMPOSITE_INDEXES = [
    ("idx_margin_requirements_member_instrument",
     "margin_requirements", "member_id, instrument_id"),
    ("idx_state_transitions_entity",
     "state_transitions", "entity_type, entity_id"),
    ("idx_price_feeds_instrument_received",
     "price_feeds", "instrument_id, received_at DESC"),
]


def upgrade():
    for name, table, columns in INDEXES:
        op.execute(
            f"CREATE INDEX {name} ON {table} ({columns})"
        )

    for name, table, columns in COMPOSITE_INDEXES:
        op.execute(
            f"CREATE INDEX {name} ON {table} ({columns})"
        )


def downgrade():
    for name, _, _ in reversed(COMPOSITE_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")

    for name, _, _ in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
