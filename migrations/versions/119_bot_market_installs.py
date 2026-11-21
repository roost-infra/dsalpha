"""Migration 119: record the built-in Bot market's installs.

The market itself is a code-shipped catalogue (``services/bot_market``): the
platform's built-in Bot templates, versioned with the build. Nothing in the
database lists them. What the database needs is one row per install, so a
buyer can see where they installed a template and which Bot row it became.

``bot_market_installs`` is that journal. It is append-only: uninstalling a Bot
does not delete its history, and the Bot row is the live thing (deleting it
cascades this row away, which is why the foreign key carries ``ON DELETE
CASCADE``). ``listing_slug`` and ``listing_version`` are what the install was,
not a foreign key, because the catalogue lives in the build.

Rollback: ``alembic downgrade 118``. Dropping the table loses the install
history but not the Bot rows the installs created.
"""

from alembic import op

revision = "119"
down_revision = "118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_market_installs (
            install_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         VARCHAR(255) NOT NULL
                REFERENCES users(user_id) ON DELETE CASCADE,
            listing_slug    TEXT NOT NULL,
            listing_version TEXT NOT NULL,
            workspace_id    UUID NOT NULL
                REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
            bot_id          UUID NOT NULL
                REFERENCES bots(bot_id) ON DELETE CASCADE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_market_installs_buyer "
        "ON bot_market_installs (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_market_installs_slug "
        "ON bot_market_installs (user_id, listing_slug)"
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("DROP INDEX IF EXISTS ix_bot_market_installs_slug")
    op.execute("DROP INDEX IF EXISTS ix_bot_market_installs_buyer")
    op.execute("DROP TABLE IF EXISTS bot_market_installs")
    op.execute("RESET lock_timeout")
