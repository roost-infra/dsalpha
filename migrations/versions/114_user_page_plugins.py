"""The built-in page plugins a user has switched on.

Page plugins are shipped inside the app; this table records only the enable
switch, one row per user and plugin. A missing row means the plugin's default
(the app ships every page plugin disabled until the user turns it on).

Revision ID: 114
Revises: 113
Rollback: ``alembic downgrade 113``
"""

import sqlalchemy as sa
from alembic import op

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_page_plugins (
            user_id    VARCHAR(255) NOT NULL
                REFERENCES users(user_id) ON DELETE CASCADE,
            plugin_id  VARCHAR(64) NOT NULL,
            enabled    BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, plugin_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_page_plugins_enabled "
        "ON user_page_plugins (user_id) WHERE enabled"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_page_plugins")
