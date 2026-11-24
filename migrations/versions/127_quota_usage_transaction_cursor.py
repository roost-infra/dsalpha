"""Stamp new usage rows with the writer transaction for quota ingestion."""

from alembic import op

revision = "127"
down_revision = "126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Set the volatile default after adding the column to preserve old rows
    # and avoid rewriting the table. The index starts out empty.
    op.execute("ALTER TABLE conversation_usages ADD COLUMN quota_ingest_xid xid8")
    op.execute("""
        ALTER TABLE conversation_usages
            ALTER COLUMN quota_ingest_xid SET DEFAULT pg_current_xact_id()
    """)
    op.execute("""
        CREATE INDEX conversation_usages_quota_ingest_xid_idx
            ON conversation_usages (quota_ingest_xid, conversation_usage_id)
            WHERE quota_ingest_xid IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE conversation_usages DROP COLUMN quota_ingest_xid")
