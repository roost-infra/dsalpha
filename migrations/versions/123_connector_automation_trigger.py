"""Migration 123: allow ``connector`` as an automation trigger.

A connector automation is event-driven: its next_run_at stays NULL, so the
due-automation poller never claims it. The Composio webhook handler matches
its trigger_config and dispatches the run itself.
"""

from alembic import op

revision = "123"
down_revision = "122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        """
        ALTER TABLE automations
        DROP CONSTRAINT IF EXISTS automations_trigger_type_check
        """
    )
    op.execute(
        """
        ALTER TABLE automations
        ADD CONSTRAINT automations_trigger_type_check
        CHECK (trigger_type IN ('cron', 'once', 'price', 'connector'))
        """
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    # A connector row has no schedule the poller can read; removing the kind
    # must remove the rows that would otherwise violate the old constraint.
    op.execute("DELETE FROM automations WHERE trigger_type = 'connector'")
    op.execute(
        "ALTER TABLE automations DROP CONSTRAINT IF EXISTS automations_trigger_type_check"
    )
    op.execute(
        """
        ALTER TABLE automations
        ADD CONSTRAINT automations_trigger_type_check
        CHECK (trigger_type IN ('cron', 'once', 'price'))
        """
    )
    op.execute("RESET lock_timeout")
