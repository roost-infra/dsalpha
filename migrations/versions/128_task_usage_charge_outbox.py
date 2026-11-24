"""Keep task usage charges independent of conversation deletion."""

from alembic import op

revision = "128"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("""
        ALTER TABLE hook_outbox
            ALTER COLUMN conversation_thread_id DROP NOT NULL,
            ADD CONSTRAINT hook_outbox_thread_required
                CHECK (conversation_thread_id IS NOT NULL OR hook_type = 'task_usage_charge')
                NOT VALID
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM hook_outbox
                WHERE conversation_thread_id IS NULL AND status <> 'done'
            ) THEN
                RAISE EXCEPTION 'Reconcile unresolved task usage charges before downgrading';
            END IF;
        END $$
    """)
    op.execute("DELETE FROM hook_outbox WHERE conversation_thread_id IS NULL")
    op.execute("""
        ALTER TABLE hook_outbox
            ALTER COLUMN conversation_thread_id SET NOT NULL,
            DROP CONSTRAINT hook_outbox_thread_required
    """)
