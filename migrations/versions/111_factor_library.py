"""The factor library: the durable rows behind the board.

The board could already run a factor once and show the verdict, but nothing kept
the factor. A run was process-local and expired, so a good factor was gone as
soon as the page was reloaded or the worker restarted -- and a factor that cannot
be found again cannot be promoted, compared or reused. This table is what makes a
factor an asset rather than an experiment.

``hypothesis`` is NOT NULL on purpose. Every factor carries the economic reason
someone believes it works, and the board renders it above the code: an unexplained
factor is data mining, and the schema is the cheapest place to refuse one. A
NULL-able column would let the API forget the check.

``metrics`` is JSONB rather than columns because it is the factor-miner's
tearsheet -- quantile returns, IC decay, long/short spread, turnover -- a nested
shape owned by another service that will keep growing fields. Flattening it here
would mean a migration per miner release and a lossy mapping in the meantime; the
board renders it as it arrives. ``last_evaluated_at`` is lifted out of the JSON
only because it is *queried* ("what has gone stale"), not because it is rendered.

``code_hash`` (md5 of ``code``) is stored next to the code so a re-save can tell
"same factor, edited text fields" from "same name, different factor": the second
must drop the metrics and demote the factor, because those metrics describe code
that no longer exists. Deciding that in SQL against a hash is what keeps a stale
tearsheet from being shown as a current one.

``(user_id, name)`` is unique because the board's save action is idempotent by
name -- typing the same factor name again must mean "update it", not "make a
second one nobody can tell apart". ``source`` records who wrote it (user, agent,
sota baseline, athena import) because the board shows trust: a baseline and a
model's guess are not the same claim.

Revision ID: 044
Revises: 043
"""

from alembic import op

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None

# Written out rather than imported from the service so the constraint is readable
# in psql and cannot drift when the Python tuple is edited (same reasoning as 043).
_STATUSES = ("candidate", "promoted", "rejected")


def upgrade() -> None:
    statuses = ", ".join(f"'{status}'" for status in _STATUSES)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS factor_library (
            factor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id VARCHAR(255) NOT NULL
                REFERENCES users(user_id) ON DELETE CASCADE,
            name VARCHAR(64) NOT NULL,
            hypothesis TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            formulation TEXT NOT NULL DEFAULT '',
            variables JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            code TEXT NOT NULL,
            code_hash CHAR(32) NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'user',
            status VARCHAR(16) NOT NULL DEFAULT 'candidate'
                CHECK (status IN ({statuses})),
            metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            last_evaluated_at TIMESTAMPTZ,
            promoted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_factor_library_user_name "
        "ON factor_library (user_id, name)"
    )
    # The board's default read is "my factors, optionally by status", newest first.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_factor_library_user_status "
        "ON factor_library (user_id, status, updated_at DESC)"
    )
    # Same code under two names is a duplicate the board wants to surface, so it
    # is looked up by hash rather than by name.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_factor_library_user_hash "
        "ON factor_library (user_id, code_hash)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS factor_library CASCADE")
