"""Migration 122: the managed-broker token for a Connected Apps installation.

When a deployment supplies one Composio project key, the connector must not
hand that key to every user's vault. The installation instead carries the hash
of a per-account bearer token; the token itself lives in that user's vault and
authenticates the server-side MCP proxy, which adds the shared key upstream.

Rollback only removes the hash column. The broker URL and token are connector
and vault data, left untouched.
"""

from alembic import op

revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE connected_app_installations "
        "ADD COLUMN IF NOT EXISTS proxy_token_hash TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_connected_app_installations_proxy "
        "ON connected_app_installations (proxy_token_hash) "
        "WHERE proxy_token_hash IS NOT NULL"
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("DROP INDEX IF EXISTS ix_connected_app_installations_proxy")
    op.execute(
        "ALTER TABLE connected_app_installations DROP COLUMN IF EXISTS proxy_token_hash"
    )
    op.execute("RESET lock_timeout")
