"""Migration 121: per-bot connector tool grants.

One JSON object per bot, shaped like ``{"github": {"tools": "*"}}`` or
``{"github": {"tools": ["GITHUB_CREATE_AN_ISSUE"]}}``. An empty object means
the bot has no restriction (every connector tool); once the object names any
app, an app it omits grants that bot nothing. This mirrors OpenMausBot's
per-bot connector grants and lives on the bot row, where the rest of the bot's
tool surface already lives.
"""

from alembic import op

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE bots ADD COLUMN IF NOT EXISTS connector_tools "
        "JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("ALTER TABLE bots DROP COLUMN IF EXISTS connector_tools")
    op.execute("RESET lock_timeout")
