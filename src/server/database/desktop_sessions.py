from src.server.database.pool import get_db_connection


async def set_desktop_state(computer: dict, state: str, transport: str) -> bool:
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            """UPDATE computers c SET desktop_state=%s, desktop_transport=%s
               WHERE c.computer_id=%s AND c.user_id=%s AND c.provider_ref=%s AND c.status='running'
               AND (SELECT started_at FROM computer_runs r
                    WHERE r.computer_id=c.computer_id AND r.ended_at IS NULL)
                   IS NOT DISTINCT FROM %s::timestamptz""",
            (state, transport, computer["computer_id"], computer["user_id"],
             computer["provider_ref"], computer.get("running_since")),
        )
        return bool(cursor.rowcount)


async def opened(session) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """INSERT INTO computer_desktop_sessions
               (session_id, computer_id, user_id, role, transport, provider_ref)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (session.session_id, session.computer_id, session.user_id, session.role,
             session.transport, session.provider_ref),
        )


async def record(session_id: str, received: int, sent: int, *, reason: str | None = None) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """UPDATE computer_desktop_sessions
               SET last_seen_at=now(), bytes_in=%s, bytes_out=%s, end_reason=%s,
                   ended_at=CASE WHEN %s::boolean THEN now() ELSE NULL END
               WHERE session_id=%s AND ended_at IS NULL""",
            (received, sent, reason, reason is not None, session_id),
        )


async def close_stale() -> None:
    """A worker that lost its socket or lease can leave no final audit write."""
    async with get_db_connection() as conn:
        await conn.execute(
            """UPDATE computer_desktop_sessions SET ended_at=last_seen_at, end_reason='interrupted'
               WHERE ended_at IS NULL AND last_seen_at < now() - interval '2 minutes'"""
        )
