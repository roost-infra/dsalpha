"""Migration 120: connected-app installations.

One row per user maps to one Composio project user and its Tool Router session
(the hosted MCP endpoint whose tools that user's bots may call). The key itself
is never stored here: it lives in the user's vault as ``COMPOSIO_API_KEY`` and
the generated connector references it as ``${vault:COMPOSIO_API_KEY}``.

Rollback drops the mapping. The connector row and vault secret it created are
user data and are left alone.
"""

from alembic import op

revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connected_app_installations (
            user_id           VARCHAR(255) PRIMARY KEY
                REFERENCES users(user_id) ON DELETE CASCADE,
            composio_user_id  VARCHAR(255) NOT NULL,
            session_id        VARCHAR(255) NOT NULL,
            mcp_url           TEXT NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_connected_app_installations_session "
        "ON connected_app_installations (session_id)"
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("DROP INDEX IF EXISTS ix_connected_app_installations_session")
    op.execute("DROP TABLE IF EXISTS connected_app_installations")
    op.execute("RESET lock_timeout")
