"""Existing accounts keep the Market Center entry they had before page plugins.

Page plugins ship off by default for new accounts. Accounts that existed when
the page-plugin switch was introduced already had Market in the primary nav, so
backfill their switch to on; a later explicit disable still wins because the
insert does not overwrite an existing row.

Revision ID: 115
Revises: 114
Rollback: ``alembic downgrade 114``
"""

from alembic import op

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        INSERT INTO user_page_plugins (user_id, plugin_id, enabled, updated_at)
        SELECT user_id, 'market-center', TRUE, NOW()
        FROM users
        ON CONFLICT (user_id, plugin_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # The backfill cannot distinguish users who enabled the plugin themselves
    # from users this migration enabled. Rolling back removes only rows the
    # migration could have written; the table itself stays for 114's rollback.
    op.execute(
        """
        DELETE FROM user_page_plugins
        WHERE plugin_id = 'market-center' AND enabled = TRUE
        """
    )
