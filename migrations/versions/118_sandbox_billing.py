"""Migration 118: billing a closed sandbox run to Roost Console.

``computer_runs`` records how long a metered sandbox ran and how big it was
(088), but nothing marked which of those runs has been charged. The console's
``POST /internal/v1/usage/sandbox`` debits an organization's wallet once per
idempotency key, and dslpha needs somewhere to remember the answer: a crash
between the console accepting a report and this process recording it must not
make the run billable again, and a run the console refused must not be retried
forever.

``billing_reported_at`` is the settled marker. It is set when the run has no
further billing to do: the console accepted the report (201 fresh, 200 replay),
the report was permanently rejected (a malformed body, an out-of-range figure),
or the run has nothing billable in it (zero seconds, no configured resource).
It is left NULL when the failure is worth another attempt -- 402 insufficient
credits, 401/403 a bad service secret or missing scope, 404 no organization for
the user yet, 429/5xx/network -- and ``billing_error`` says what happened last.
``billing_credits`` is the integer total charged (0 for a run with nothing to
bill); it is NULL when only an error is recorded.

Two billing properties are deliberately absent. Runs are reported only for the
interval they spent running: a stopped sandbox keeps its disk, but the ledger
has no pause row or disk-only interval, so that storage is not billed yet. And
nothing is backfilled: the first reporter pass after this deploy charges the
closed runs whose ``billing_reported_at`` is still NULL, which are exactly the
runs that closed after 088 shipped.

The partial index is the reporter's queue: closed, unreported runs in end
order. Writing the three columns on an existing row rewrites that row, and the
index is built over the few closed runs that have not been billed yet, so both
statements are short. The previous build never reads or writes these columns.

Rollback: ``alembic downgrade 117``. It drops the columns and the index, and
the console's idempotency keys keep the runs already reported from being
charged twice if a later build reports them again; unreported runs are simply
not billed until this revision is applied again.
"""

from alembic import op

revision = "118"
down_revision = "117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE computer_runs "
        "ADD COLUMN IF NOT EXISTS billing_reported_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS billing_credits BIGINT, "
        "ADD COLUMN IF NOT EXISTS billing_error TEXT"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_computer_runs_billing_due
        ON computer_runs (provider_kind, ended_at)
        WHERE ended_at IS NOT NULL AND billing_reported_at IS NULL
    """)
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("DROP INDEX IF EXISTS idx_computer_runs_billing_due")
    op.execute(
        "ALTER TABLE computer_runs "
        "DROP COLUMN IF EXISTS billing_error, "
        "DROP COLUMN IF EXISTS billing_credits, "
        "DROP COLUMN IF EXISTS billing_reported_at"
    )
    op.execute("RESET lock_timeout")
