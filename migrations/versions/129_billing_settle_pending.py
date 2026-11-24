"""Migration 129: no run is released without a spend figure.

The compatibility release used to read the run's ``in_flight_credits`` and
release the lease with whatever it found. A read failure (or a row the run
never wrote) settled nothing and retired the reservation anyway, so the console
released the whole ceiling and the turn was given away. dslpha has a second,
durable record of what the run spent — the ``conversation_usages`` row its
finalize writes — but finalize commits *after* the gate tears down, so the
release cannot always wait for it.

These columns make the failure visible and recovery possible:

* ``billing_settle_pending`` marks a run whose lease was deliberately not
  released because no spend figure was available. The settlement worker reads
  the run's usage row once finalize has committed it and releases then.
* ``billing_settle_pending_at`` is the marker's clock (the queue order) and the
  grace the worker waits out before settling, so it does not race the very
  finalize transaction it needs.
* ``billing_settle_error`` records why the last attempt did not settle, which
  is what an operator reads when a run stays pending.
* ``billing_settled_at`` / ``billing_charged_credits`` record a successful
  release: the console's ``charged_credits`` is the only place the priced
  amount for a ``model_usage`` release exists, and keeping it on the run makes
  ``ledger`` vs local reconciliation possible.

The partial index is the worker's queue: pending, unsettled rows in pending
order. It is built over the rows that are pending at deploy time (normally
none), so it is cheap to create; the columns are nullable/defaulted and never
read by the previous build.

Rollback: ``alembic downgrade 128``. Dropping the columns loses which runs were
waiting to settle; the console's idempotency keys keep a run already released
from being charged twice if a later build re-reports it.
"""

from alembic import op

revision = "129"
down_revision = "128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        "ALTER TABLE conversation_responses "
        "ADD COLUMN IF NOT EXISTS billing_settle_pending BOOLEAN NOT NULL "
        "DEFAULT FALSE, "
        "ADD COLUMN IF NOT EXISTS billing_settle_pending_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS billing_settle_error TEXT, "
        "ADD COLUMN IF NOT EXISTS billing_settled_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS billing_charged_credits BIGINT"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversation_responses_settle_pending
        ON conversation_responses (billing_settle_pending_at)
        WHERE billing_settle_pending AND billing_settled_at IS NULL
    """)
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(
        "DROP INDEX IF EXISTS idx_conversation_responses_settle_pending"
    )
    op.execute(
        "ALTER TABLE conversation_responses "
        "DROP COLUMN IF EXISTS billing_charged_credits, "
        "DROP COLUMN IF EXISTS billing_settled_at, "
        "DROP COLUMN IF EXISTS billing_settle_error, "
        "DROP COLUMN IF EXISTS billing_settle_pending_at, "
        "DROP COLUMN IF EXISTS billing_settle_pending"
    )
    op.execute("RESET lock_timeout")
