"""Guest bot DM: invite-gated cross-tenant bot contacts.

A platform deployment holds many users' bots in one database. A bot may reach a
bot of another account only when the receiving owner issued an invite for that
bot and accepted the first contact; the receiving owner pays for the turns the
guest conversation triggers.

Revision ID: 117
Revises: 116
Rollback: ``alembic downgrade 116``
"""

from alembic import op

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")

    # One link per invite. Only the hash is stored: a database dump cannot be
    # replayed as a working invite.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_dm_invites (
            invite_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bot_id         UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
            owner_user_id  VARCHAR(255) NOT NULL
                           REFERENCES users(user_id) ON DELETE CASCADE,
            token_hash     CHAR(64) NOT NULL UNIQUE,
            created_by     VARCHAR(255) NOT NULL,
            expires_at     TIMESTAMPTZ,
            max_uses       INTEGER NOT NULL DEFAULT 1 CHECK (max_uses > 0),
            uses           INTEGER NOT NULL DEFAULT 0,
            status         VARCHAR(16) NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'revoked')),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_dm_invites_owner "
        "ON bot_dm_invites (owner_user_id, bot_id, created_at DESC)"
    )

    # Consent is a pair of directional rows: the receiver's row is the one that
    # admits delivery, the sender's row is the mirror written on accept so a
    # reply can come back without a second approval.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_dm_contacts (
            owner_user_id  VARCHAR(255) NOT NULL
                           REFERENCES users(user_id) ON DELETE CASCADE,
            bot_id         UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
            peer_bot_id    UUID NOT NULL REFERENCES bots(bot_id) ON DELETE CASCADE,
            peer_user_id   VARCHAR(255) NOT NULL,
            status         VARCHAR(16) NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'accepted', 'blocked')),
            invite_id      UUID REFERENCES bot_dm_invites(invite_id)
                           ON DELETE SET NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (bot_id, peer_bot_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_dm_contacts_owner "
        "ON bot_dm_contacts (owner_user_id, status, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_dm_contacts_peer "
        "ON bot_dm_contacts (peer_bot_id, status)"
    )

    # bot_messages already carries the durable inbox; guest messages add the
    # sender's account and display name, and a flag the delivery path and the
    # UI can branch on.
    op.execute(
        "ALTER TABLE bot_messages "
        "ADD COLUMN IF NOT EXISTS from_user_id VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE bot_messages "
        "ADD COLUMN IF NOT EXISTS from_name VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE bot_messages "
        "ADD COLUMN IF NOT EXISTS external BOOLEAN NOT NULL DEFAULT FALSE"
    )
    # The inline CHECK in 112 got a generated name; find it by definition
    # instead of guessing, then install the widened one under a stable name.
    op.execute(
        """
        DO $$
        DECLARE c RECORD;
        BEGIN
            FOR c IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'bot_messages'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%from_type%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE bot_messages DROP CONSTRAINT %I', c.conname
                );
            END LOOP;
        END $$;
        """
    )
    op.execute(
        "ALTER TABLE bot_messages ADD CONSTRAINT bot_messages_from_type_check "
        "CHECK (from_type IN ('bot', 'user', 'system', 'guest_bot'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_messages_external_from "
        "ON bot_messages (from_user_id, created_at DESC) "
        "WHERE external"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_messages_external_inbox "
        "ON bot_messages (to_bot_id, status) WHERE external"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_bot_messages_external_inbox")
    op.execute("DROP INDEX IF EXISTS ix_bot_messages_external_from")
    op.execute(
        "ALTER TABLE bot_messages DROP CONSTRAINT IF EXISTS bot_messages_from_type_check"
    )
    op.execute(
        "ALTER TABLE bot_messages ADD CONSTRAINT bot_messages_from_type_check "
        "CHECK (from_type IN ('bot', 'user', 'system'))"
    )
    op.execute("ALTER TABLE bot_messages DROP COLUMN IF EXISTS external")
    op.execute("ALTER TABLE bot_messages DROP COLUMN IF EXISTS from_name")
    op.execute("ALTER TABLE bot_messages DROP COLUMN IF EXISTS from_user_id")
    op.execute("DROP TABLE IF EXISTS bot_dm_contacts")
    op.execute("DROP TABLE IF EXISTS bot_dm_invites")
