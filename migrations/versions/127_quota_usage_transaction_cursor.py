"""Stamp new usage rows with the writer transaction for quota ingestion."""

from alembic import op

revision = "127"
down_revision = "126"
branch_labels = None
depends_on = None

_USAGE_XID_INDEX = "conversation_usages_quota_ingest_xid_idx"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # Set the volatile default after adding the column to preserve old rows
    # and avoid rewriting the table. The concurrent build commits that DDL,
    # so a retry must accept a column from an earlier interrupted upgrade.
    op.execute("ALTER TABLE conversation_usages ADD COLUMN IF NOT EXISTS quota_ingest_xid xid8")
    op.execute("""
        ALTER TABLE conversation_usages
            ALTER COLUMN quota_ingest_xid SET DEFAULT pg_current_xact_id()
    """)
    with op.get_context().autocommit_block():
        # The concurrent build can wait for existing transactions without
        # blocking ordinary writes. A short lock timeout can leave it invalid.
        op.execute("SET lock_timeout = 0")
        # A failed concurrent build can leave an invalid index of this name.
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_USAGE_XID_INDEX}")
        op.execute(f"""
            CREATE INDEX CONCURRENTLY {_USAGE_XID_INDEX}
                ON conversation_usages (quota_ingest_xid, conversation_usage_id)
                WHERE quota_ingest_xid IS NOT NULL
        """)
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("ALTER TABLE conversation_usages DROP COLUMN quota_ingest_xid")
