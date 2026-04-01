"""Create database roles

Revision ID: 001
Revises: None
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def _create_role_if_not_exists(name: str) -> str:
    return (
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') "
        f"THEN CREATE ROLE {name} NOLOGIN; END IF; END $$"
    )


def upgrade():
    op.execute(_create_role_if_not_exists("readonly_user"))
    op.execute(
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT ON TABLES TO readonly_user"
    )

    op.execute(_create_role_if_not_exists("ledger_user"))

    op.execute(_create_role_if_not_exists("admin_user"))
    op.execute(
        "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO admin_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL PRIVILEGES ON TABLES TO admin_user"
    )


def downgrade():
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON TABLES FROM admin_user"
    )
    op.execute("DROP ROLE IF EXISTS admin_user")

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON TABLES FROM ledger_user"
    )
    op.execute("DROP ROLE IF EXISTS ledger_user")

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT ON TABLES FROM readonly_user"
    )
    op.execute("DROP ROLE IF EXISTS readonly_user")
