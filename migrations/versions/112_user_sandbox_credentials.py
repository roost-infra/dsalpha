"""Per-user sandbox provider credentials (BYOK).

A deployment normally holds one sandbox account (DAYTONA_API_KEY). This table
lets a user bring their own key instead: the key is encrypted app-side
(AES-GCM under BYOK_ENCRYPTION_KEY) so a computer's provider can be built
synchronously, without a database round trip.

Existing computers keep the ciphertext their provider_config snapshotted at
create time; deleting a row stops new computers from using it but does not
revoke machines already built with it.

Revision ID: 112
Revises: 111
"""

from alembic import op

revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sandbox_credentials (
            user_id VARCHAR(255) NOT NULL
                REFERENCES users(user_id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL,
            api_key_encrypted TEXT NOT NULL,
            base_url VARCHAR(512),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, kind)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_sandbox_credentials")
