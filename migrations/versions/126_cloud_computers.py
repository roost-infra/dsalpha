"""Migration 126: cloud computer platform, desktop status, and desktop session history."""

from alembic import op

revision = "126"
down_revision = "125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # The SSH probe and reconnect already persist the actual OS. Derive these
    # fields from the effective provider settings, including for legacy rows.
    op.execute("""
        ALTER TABLE computers
            ADD COLUMN os_platform varchar(16) GENERATED ALWAYS AS (
                CASE WHEN kind = 'ssh' THEN CASE provider_config->>'os'
                    WHEN 'Darwin' THEN 'macos' WHEN 'Linux' THEN 'linux' END
                    ELSE 'linux' END
            ) STORED,
            ADD COLUMN region text GENERATED ALWAYS AS (provider_config->>'target') STORED,
            ADD COLUMN os_image text GENERATED ALWAYS AS (provider_config->>'image') STORED,
            ADD COLUMN desktop_transport varchar(16)
                CHECK (desktop_transport IN ('novnc', 'vnc-ws', 'screenshot')),
            ADD COLUMN desktop_state varchar(16) NOT NULL DEFAULT 'off'
                CHECK (desktop_state IN ('off', 'starting', 'ready', 'error')),
            ADD COLUMN reservation_id varchar(64),
            ADD COLUMN reservation_expires_at timestamptz
    """)
    op.execute("""
        CREATE FUNCTION reset_computer_desktop_state() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.desktop_state := 'off';
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER computers_reset_desktop_state
            BEFORE UPDATE OF status, provider_ref ON computers
            FOR EACH ROW
            WHEN (OLD.status IS DISTINCT FROM NEW.status
                  OR OLD.provider_ref IS DISTINCT FROM NEW.provider_ref)
            EXECUTE FUNCTION reset_computer_desktop_state()
    """)
    op.execute("""
        CREATE TABLE computer_desktop_sessions (
            session_id uuid PRIMARY KEY,
            computer_id uuid NOT NULL REFERENCES computers(computer_id) ON DELETE CASCADE,
            user_id varchar(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role varchar(16) NOT NULL CHECK (role IN ('control', 'view')),
            transport varchar(16) NOT NULL CHECK (transport IN ('novnc', 'vnc-ws', 'screenshot')),
            provider_ref text NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            ended_at timestamptz,
            end_reason text,
            bytes_in bigint NOT NULL DEFAULT 0 CHECK (bytes_in >= 0),
            bytes_out bigint NOT NULL DEFAULT 0 CHECK (bytes_out >= 0)
        )
    """)
    op.execute("""
        CREATE INDEX computer_desktop_sessions_computer_started
            ON computer_desktop_sessions (computer_id, started_at DESC)
    """)
    op.execute("""
        CREATE INDEX computer_desktop_sessions_last_seen
            ON computer_desktop_sessions (last_seen_at) WHERE ended_at IS NULL
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("DROP TABLE computer_desktop_sessions")
    op.execute("DROP TRIGGER IF EXISTS computers_reset_desktop_state ON computers")
    op.execute("DROP FUNCTION IF EXISTS reset_computer_desktop_state()")
    op.execute("""
        ALTER TABLE computers
            DROP COLUMN reservation_expires_at, DROP COLUMN reservation_id,
            DROP COLUMN desktop_state, DROP COLUMN desktop_transport,
            DROP COLUMN os_image, DROP COLUMN region, DROP COLUMN os_platform
    """)
