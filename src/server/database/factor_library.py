"""Postgres store for the factor library.

One row per factor a user keeps: the code, the economic hypothesis behind it, the
lifecycle status, and the factor-miner's last tearsheet. The table's reasoning
(why ``hypothesis`` is NOT NULL, why ``metrics`` is JSONB, why ``code_hash`` sits
next to the code) is in ``migrations/versions/044_factor_library.py``.

Two things here are not obvious from the SQL:

- A save is an upsert by ``(user_id, name)``, and it is **not** a blind update.
  When the code changed, the stored metrics describe code that no longer exists,
  so they are dropped and the factor is demoted to ``candidate``. Deciding that
  in one statement (against the row's *old* hash) is what stops the board from
  rendering a stale tearsheet as a current one -- the failure would look like a
  correct number rather than an error.
- Evaluation state rides in ``metrics``. The row is the truth about whether an
  evaluation is running, finished or lost, because the request that started it
  lives in one worker's memory and any worker may be the one that reads next.
"""

import hashlib
import logging
from typing import Any

from psycopg.rows import dict_row

from src.server.database.pool import get_db_connection
from src.server.utils.pg_sanitize import SafeJson, strip_pg_nul_str

logger = logging.getLogger(__name__)

# Returned by every read path so a route never has to know the column list, and
# so ``SELECT *`` (which would leak into the API shape) is never tempting.
_COLUMNS = """
    factor_id, name, hypothesis, description, formulation, variables,
    code, code_hash, source, status, metrics,
    last_evaluated_at, promoted_at, created_at, updated_at
"""

# A library is browsed, not scanned: the cap keeps a runaway insert loop from
# turning the list endpoint into a multi-megabyte response (each row carries a
# full tearsheet in ``metrics``).
_MAX_ROWS = 500

_INSERT_SQL = f"""
    INSERT INTO factor_library
        (user_id, name, hypothesis, description, formulation, variables,
         code, code_hash, source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING {_COLUMNS}
"""

# ``status``/``metrics``/``promoted_at`` are compared against the row's *old*
# ``code_hash`` (Postgres evaluates SET expressions against the old tuple), so an
# unchanged code keeps its verdict and an edited one starts over.
_UPDATE_SQL = f"""
    UPDATE factor_library
    SET hypothesis = %s,
        description = %s,
        formulation = %s,
        variables = %s,
        code = %s,
        code_hash = %s,
        source = %s,
        status = CASE WHEN code_hash = %s THEN status ELSE 'candidate' END,
        promoted_at = CASE WHEN code_hash = %s THEN promoted_at ELSE NULL END,
        metrics = CASE WHEN code_hash = %s THEN metrics ELSE '{{}}'::jsonb END,
        last_evaluated_at = CASE WHEN code_hash = %s THEN last_evaluated_at ELSE NULL END,
        updated_at = NOW()
    WHERE user_id = %s AND name = %s
    RETURNING {_COLUMNS}
"""

_SELECT_BY_ID_SQL = f"""
    SELECT {_COLUMNS}
    FROM factor_library
    WHERE user_id = %s AND factor_id = %s
"""

_DELETE_SQL = """
    DELETE FROM factor_library
    WHERE user_id = %s AND factor_id = %s
    RETURNING factor_id
"""

_STATUS_SQL = f"""
    UPDATE factor_library
    SET status = %s,
        promoted_at = CASE WHEN %s = 'promoted' THEN NOW() ELSE NULL END,
        updated_at = NOW()
    WHERE user_id = %s AND factor_id = %s
    RETURNING {_COLUMNS}
"""


def code_hash_of(code: str) -> str:
    """md5 hex of the factor source. The value the re-save rule compares on."""
    return hashlib.md5(code.encode("utf-8")).hexdigest()


def _list_filters(
    user_id: str,
    status: str | None,
    source: str | None,
    query: str | None,
) -> tuple[str, list[Any]]:
    """Build the WHERE clause for the list read, always user-scoped first."""
    where = ["user_id = %s"]
    params: list[Any] = [user_id]
    if status:
        where.append("status = %s")
        params.append(status)
    if source:
        where.append("source = %s")
        params.append(source)
    if query:
        # Name and hypothesis: the two fields the board's search box shows a hit
        # for, so matching either one is a hit the user can see.
        where.append("(name ILIKE %s OR hypothesis ILIKE %s)")
        like = f"%{query}%"
        params.extend([like, like])
    return " AND ".join(where), params


async def save_factor(
    user_id: str,
    *,
    name: str,
    hypothesis: str,
    code: str,
    description: str = "",
    formulation: str = "",
    variables: dict[str, Any] | None = None,
    source: str = "user",
) -> dict[str, Any]:
    """Insert or update one factor, keyed by ``(user_id, name)``.

    Runs both branches on one pooled connection inside one transaction: the read
    that decides insert-vs-update and the write that follows must not be
    interleaved with another save of the same name (the unique index would
    otherwise turn a race into a 500 instead of an update).
    """
    code_hash = code_hash_of(code)
    variables_json = SafeJson(variables or {})
    clean = lambda value: strip_pg_nul_str(value)

    async with get_db_connection() as conn, conn.transaction():
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT code_hash FROM factor_library WHERE user_id = %s AND name = %s",
                (user_id, clean(name)),
            )
            existing = await cur.fetchone()
            if existing is None:
                await cur.execute(
                    _INSERT_SQL,
                    (
                        user_id,
                        clean(name),
                        clean(hypothesis),
                        clean(description),
                        clean(formulation),
                        variables_json,
                        code,
                        code_hash,
                        clean(source),
                    ),
                )
            else:
                await cur.execute(
                    _UPDATE_SQL,
                    (
                        clean(hypothesis),
                        clean(description),
                        clean(formulation),
                        variables_json,
                        code,
                        code_hash,
                        clean(source),
                        code_hash,
                        code_hash,
                        code_hash,
                        code_hash,
                        user_id,
                        clean(name),
                    ),
                )
            return await cur.fetchone()


async def list_factors(
    user_id: str,
    *,
    status: str | None = None,
    source: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """This user's factors, newest first."""
    where, params = _list_filters(user_id, status, source, query)
    sql = f"""
        SELECT {_COLUMNS}
        FROM factor_library
        WHERE {where}
        ORDER BY updated_at DESC
        LIMIT %s
    """
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, [*params, _MAX_ROWS])
            return await cur.fetchall()


async def status_counts(user_id: str) -> dict[str, int]:
    """Per-status totals for the board's filter chips (one round trip, no scan)."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'candidate') AS candidate,
                    COUNT(*) FILTER (WHERE status = 'promoted') AS promoted,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                    COUNT(*) FILTER (WHERE metrics ? 'tearsheet') AS evaluated
                FROM factor_library
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = await cur.fetchone()
    return {key: int(value or 0) for key, value in (row or {}).items()}


async def get_factor(user_id: str, factor_id: str) -> dict[str, Any] | None:
    """One factor, or None when it is not this user's (or does not exist)."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SELECT_BY_ID_SQL, (user_id, factor_id))
            return await cur.fetchone()


async def delete_factor(user_id: str, factor_id: str) -> bool:
    """Delete one factor; returns whether a row was there to delete."""
    async with get_db_connection() as conn, conn.cursor() as cur:
        await cur.execute(_DELETE_SQL, (user_id, factor_id))
        return await cur.fetchone() is not None


async def set_status(user_id: str, factor_id: str, status: str) -> dict[str, Any] | None:
    """Move a factor through its lifecycle. ``promoted_at`` is derived, not passed."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_STATUS_SQL, (status, status, user_id, factor_id))
            return await cur.fetchone()


async def write_metrics(
    user_id: str,
    factor_id: str,
    *,
    metrics: dict[str, Any],
    measured: bool,
) -> dict[str, Any] | None:
    """Replace ``metrics``, stamping ``last_evaluated_at`` only when measured.

    A failed attempt and the ``running`` mark both replace ``metrics`` (the reason
    has to be what the board reads) with ``measured=False``: nothing was measured,
    and stamping the clock would report a fresh evaluation of a factor that has
    none.
    """
    sql = f"""
        UPDATE factor_library
        SET metrics = %s,
            last_evaluated_at = CASE WHEN %s THEN NOW() ELSE last_evaluated_at END,
            updated_at = NOW()
        WHERE user_id = %s AND factor_id = %s
        RETURNING {_COLUMNS}
    """
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                sql, (SafeJson(metrics), measured, user_id, factor_id)
            )
            return await cur.fetchone()
