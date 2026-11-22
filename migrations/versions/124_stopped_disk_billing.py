"""Migration 124: meter disk while a computer is stopped.

Daytona bills reserved disk in stopped/paused states, but computer_runs only
has running intervals. Add the watermark the stopped-disk sweeper advances, and
baseline machines already stopped at deploy time so this is not a retroactive
charge.
"""

from alembic import op

revision = "124"
down_revision = "123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE computers ADD COLUMN IF NOT EXISTS disk_billed_until timestamptz"
    )
    op.execute(
        """
        UPDATE computers
        SET disk_billed_until = NOW()
        WHERE stopped_at IS NOT NULL AND disk_billed_until IS NULL
        """
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("ALTER TABLE computers DROP COLUMN IF EXISTS disk_billed_until")
