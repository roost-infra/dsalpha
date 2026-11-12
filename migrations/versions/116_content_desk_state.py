"""Content Desk state: one optimistic-locked JSON document per user.

The page plugin is compiled into the web app; this table is the product data it
writes. A revision lets a second tab or device detect a stale write instead of
silently overwriting newer edits.

Revision ID: 116
Revises: 115
Rollback: ``alembic downgrade 115``
"""

from alembic import op

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS content_desk_states (
            user_id     TEXT PRIMARY KEY,
            payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision    BIGINT NOT NULL DEFAULT 0,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS content_desk_states")
