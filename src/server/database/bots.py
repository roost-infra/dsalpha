"""Bot persistence: the identity layer over a thread.

A bot belongs to a workspace, which stays the unit of sandbox, files and
workspace memory; the bot only adds who is speaking. The Home bot is the
Chief of Staff and is derived per user, so it is created on demand rather
than by the migration (a Home row may not exist yet).

Nothing here reads the workspace's own lifecycle: resolving which bot a turn
runs belongs to ``services/bots/resolver.py``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Iterable, Optional

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Json

from src.server.database.pool import get_db_connection
from src.server.database.user_lock import lock_user_writes
from src.server.utils.pg_sanitize import normalize_uuid

logger = logging.getLogger(__name__)

#: Hard cap on the bots a workspace may hold. Rooms allow 12; a workspace
#: still keeps room for specialists and a few paused drafts.
MAX_BOTS_PER_WORKSPACE = 20

#: Fields whose edits are worth a version row: a persona or a model change
#: silently changing every past answer's voice is what the row exists for.
VERSIONED_FIELDS = (
    "persona",
    "model",
    "provider",
    "skills",
    "tools_allow",
    "tools_deny",
    "approval",
    "memory_scopes",
)

_BOT_COLUMNS = """
    bot_id, user_id, workspace_id, name, role, persona, avatar, provider,
    model, skills, tools_allow, tools_deny, approval, memory_scopes, status,
    primary_thread_id, created_by, created_at, updated_at, deleted_at
"""


class BotNameTaken(ValueError):
    """Another live bot in the workspace already holds the name."""


class BotNotFound(ValueError):
    """No live bot by that id belongs to the caller."""


def _row_to_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    for key in ("bot_id", "workspace_id", "primary_thread_id"):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("created_at", "updated_at", "deleted_at"):
        value = out.get(key)
        if value is not None and hasattr(value, "isoformat"):
            out[key] = value.isoformat()
    return out


def _clean_bot_id(bot_id: Any) -> Optional[str]:
    return normalize_uuid(str(bot_id)) if bot_id else None


async def list_bots(
    user_id: str,
    workspace_id: Optional[str] = None,
    *,
    include_paused: bool = True,
    computer_id: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """The caller's live bots, optionally narrowed to one workspace.

    ``computer_id`` keeps a computer token's read to what that computer holds
    (Home belongs to no computer, so it is never in such a read): the ids are
    checked by subquery rather than a join, so the bot columns stay unambiguous.
    """
    where = ["user_id = %s", "deleted_at IS NULL"]
    params: list[Any] = [user_id]
    if workspace_id:
        cleaned = normalize_uuid(str(workspace_id))
        if cleaned is None:
            return []
        where.append("workspace_id = %s")
        params.append(cleaned)
    if computer_id is not None:
        where.append(
            "workspace_id IN (SELECT workspace_id FROM workspaces "
            "WHERE computer_id = %s::uuid)"
        )
        params.append(str(computer_id))
    if not include_paused:
        where.append("status = 'active'")
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_BOT_COLUMNS} FROM bots WHERE {' AND '.join(where)} "
                "ORDER BY created_at, name",
                params,
            )
            return [_row_to_dict(r) for r in await cur.fetchall()]


async def get_bot(bot_id: Any, *, conn=None) -> Optional[Dict[str, Any]]:
    """One live bot by id, or None. Owner is checked by the callers."""
    cleaned = _clean_bot_id(bot_id)
    if cleaned is None:
        return None
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_BOT_COLUMNS} FROM bots "
                "WHERE bot_id = %s AND deleted_at IS NULL",
                (cleaned,),
            )
            return _row_to_dict(await cur.fetchone())


async def get_bot_for_user(
    user_id: str, bot_id: Any, *, conn=None
) -> Optional[Dict[str, Any]]:
    cleaned = _clean_bot_id(bot_id)
    if cleaned is None:
        return None
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_BOT_COLUMNS} FROM bots "
                "WHERE bot_id = %s AND user_id = %s AND deleted_at IS NULL",
                (cleaned, user_id),
            )
            return _row_to_dict(await cur.fetchone())


async def get_bot_thread_thread_id(
    bot_id: Any, *, kind: str = "private", conn=None
) -> Optional[str]:
    """The bot's thread of ``kind``, if it already has one."""
    cleaned = _clean_bot_id(bot_id)
    if cleaned is None:
        return None
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT thread_id FROM bot_threads "
                "WHERE bot_id = %s AND kind = %s "
                "ORDER BY created_at LIMIT 1",
                (cleaned, kind),
            )
            row = await cur.fetchone()
            return str(row["thread_id"]) if row else None


async def get_workspace_bot(
    workspace_id: Any, *, role: str = "analyst", conn=None
) -> Optional[Dict[str, Any]]:
    """The workspace's default bot of a role (usually its analyst)."""
    cleaned = normalize_uuid(str(workspace_id)) if workspace_id else None
    if cleaned is None:
        return None
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_BOT_COLUMNS} FROM bots "
                "WHERE workspace_id = %s AND role = %s AND deleted_at IS NULL "
                "ORDER BY created_at LIMIT 1",
                (cleaned, role),
            )
            return _row_to_dict(await cur.fetchone())


async def get_home_bot(user_id: str, *, conn=None) -> Optional[Dict[str, Any]]:
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_BOT_COLUMNS} FROM bots "
                "WHERE user_id = %s AND role = 'chief_of_staff' "
                "AND deleted_at IS NULL ORDER BY created_at LIMIT 1",
                (user_id,),
            )
            return _row_to_dict(await cur.fetchone())


async def _insert_bot(
    *,
    user_id: str,
    workspace_id: str,
    name: str,
    role: str,
    persona: str = "",
    avatar: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    skills: Optional[Iterable[str]] = None,
    tools_allow: Optional[Iterable[str]] = None,
    tools_deny: Optional[Iterable[str]] = None,
    approval: str = "ask",
    memory_scopes: Optional[Iterable[str]] = None,
    created_by: str,
    conn=None,
) -> Dict[str, Any]:
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                INSERT INTO bots (
                    user_id, workspace_id, name, role, persona, avatar,
                    provider, model, skills, tools_allow, tools_deny,
                    approval, memory_scopes, created_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING {_BOT_COLUMNS}
                """,
                (
                    user_id,
                    workspace_id,
                    name,
                    role,
                    persona,
                    Json(avatar or {}),
                    provider,
                    model,
                    Json(list(skills or [])),
                    Json(list(tools_allow or [])),
                    Json(list(tools_deny or [])),
                    approval,
                    Json(list(memory_scopes or ["workspace"])),
                    created_by,
                ),
            )
            return _row_to_dict(await cur.fetchone())


async def create_bot(
    user_id: str,
    workspace_id: str,
    name: str,
    *,
    role: str = "analyst",
    persona: str = "",
    avatar: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    skills: Optional[Iterable[str]] = None,
    tools_allow: Optional[Iterable[str]] = None,
    tools_deny: Optional[Iterable[str]] = None,
    approval: str = "ask",
    memory_scopes: Optional[Iterable[str]] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a bot. Raises :class:`BotNameTaken` / ``ValueError`` on the cap."""
    cleaned_workspace = normalize_uuid(str(workspace_id))
    if cleaned_workspace is None:
        raise ValueError("workspace_id is not a UUID")
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await lock_user_writes(cur, user_id)
                await cur.execute(
                    "SELECT COUNT(*) AS n FROM bots "
                    "WHERE user_id = %s AND workspace_id = %s AND deleted_at IS NULL",
                    (user_id, cleaned_workspace),
                )
                if int((await cur.fetchone())["n"]) >= MAX_BOTS_PER_WORKSPACE:
                    raise ValueError(
                        f"a workspace holds at most {MAX_BOTS_PER_WORKSPACE} bots"
                    )
            try:
                return await _insert_bot(
                    user_id=user_id,
                    workspace_id=cleaned_workspace,
                    name=name,
                    role=role,
                    persona=persona,
                    avatar=avatar,
                    provider=provider,
                    model=model,
                    skills=skills,
                    tools_allow=tools_allow,
                    tools_deny=tools_deny,
                    approval=approval,
                    memory_scopes=memory_scopes,
                    created_by=created_by or user_id,
                    conn=conn,
                )
            except UniqueViolation:
                raise BotNameTaken(name) from None


async def update_bot(
    user_id: str,
    bot_id: Any,
    changes: Dict[str, Any],
    *,
    actor: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update the allowed fields, versioning the ones worth a trail."""
    cleaned = _clean_bot_id(bot_id)
    if cleaned is None:
        return None
    allowed = {
        "name",
        "persona",
        "avatar",
        "provider",
        "model",
        "skills",
        "tools_allow",
        "tools_deny",
        "approval",
        "memory_scopes",
        "status",
    }
    clean_changes = {k: v for k, v in changes.items() if k in allowed and v is not None}
    if not clean_changes:
        return await get_bot_for_user(user_id, cleaned)
    sets = []
    params: list[Any] = []
    for key, value in clean_changes.items():
        sets.append(f"{key} = %s")
        params.append(Json(value) if key in {"avatar", "skills", "tools_allow", "tools_deny", "memory_scopes"} else value)
    versioned = {k: v for k, v in clean_changes.items() if k in VERSIONED_FIELDS}
    sets.append("updated_at = NOW()")
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"UPDATE bots SET {', '.join(sets)} "
                    "WHERE bot_id = %s AND user_id = %s AND deleted_at IS NULL "
                    f"RETURNING {_BOT_COLUMNS}",
                    (*params, cleaned, user_id),
                )
                row = _row_to_dict(await cur.fetchone())
                if row is None:
                    return None
                for field, value in versioned.items():
                    await cur.execute(
                        "INSERT INTO bot_versions (bot_id, field, value, actor) "
                        "VALUES (%s, %s, %s, %s)",
                        (cleaned, field, Json(value), actor or user_id),
                    )
                return row


async def soft_delete_bot(user_id: str, bot_id: Any) -> bool:
    """Tombstone the bot; threads keep their bot_id and the row is auditable."""
    cleaned = _clean_bot_id(bot_id)
    if cleaned is None:
        return False
    async with get_db_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE bots SET deleted_at = NOW(), status = 'paused', "
                "updated_at = NOW() "
                "WHERE bot_id = %s AND user_id = %s AND deleted_at IS NULL",
                (cleaned, user_id),
            )
            return cur.rowcount > 0


async def ensure_workspace_bot(
    workspace: Dict[str, Any], *, conn=None
) -> Optional[Dict[str, Any]]:
    """The workspace's analyst bot, created on first need.

    The migration backfills every live workspace; this covers a workspace the
    resolver meets before that. Home is not such a place — it holds the
    derived Chief of Staff — so a Home row answers with that bot rather than
    minting an analyst beside it.
    """
    from src.server.database.home_workspace import is_home_row

    user_id = workspace.get("user_id")
    if is_home_row(workspace) and user_id:
        return await ensure_home_bot(str(user_id), conn=conn)
    workspace_id = normalize_uuid(str(workspace.get("workspace_id") or ""))
    if workspace_id is None or not user_id:
        return None
    existing = await get_workspace_bot(workspace_id, role="analyst", conn=conn)
    if existing is not None:
        return existing
    raw_name = str(workspace.get("name") or "").strip() or "Analyst"
    name = raw_name[:64]
    try:
        return await _insert_bot(
            user_id=str(user_id),
            workspace_id=workspace_id,
            name=name,
            role="analyst",
            created_by=str(user_id),
            conn=conn,
        )
    except UniqueViolation:
        # Another worker made it first; its row is the answer.
        return await get_workspace_bot(workspace_id, role="analyst", conn=conn)


async def ensure_home_bot(user_id: str, *, conn=None) -> Dict[str, Any]:
    """The user's Chief of Staff bot, made lazily beside their Home row."""
    existing = await get_home_bot(user_id, conn=conn)
    if existing is not None:
        return existing
    from src.server.database.workspace import get_or_create_home_workspace

    home = await get_or_create_home_workspace(user_id, conn=conn)
    try:
        return await _insert_bot(
            user_id=user_id,
            workspace_id=str(home["workspace_id"]),
            name="Chief of Staff",
            role="chief_of_staff",
            created_by=user_id,
            conn=conn,
        )
    except UniqueViolation:
        existing = await get_home_bot(user_id, conn=conn)
        if existing is None:
            raise
        return existing


async def bind_thread_bot(
    thread_id: Any, bot_id: Any, *, kind: str = "private", conn=None
) -> None:
    """Stamp the thread's bot once, and record the mapping.

    A thread may already carry another bot (a moved thread, a legacy row a
    resolver filled in); the existing owner wins, so this never rewrites.
    """
    thread = normalize_uuid(str(thread_id)) if thread_id else None
    bot = _clean_bot_id(bot_id)
    if thread is None or bot is None:
        return
    async with get_db_connection(conn) as db:
        async with db.cursor() as cur:
            await cur.execute(
                "UPDATE conversation_threads SET bot_id = %s "
                "WHERE conversation_thread_id = %s AND bot_id IS NULL",
                (bot, thread),
            )
            await cur.execute(
                "INSERT INTO bot_threads (bot_id, thread_id, kind) "
                "VALUES (%s, %s, %s) ON CONFLICT (bot_id, thread_id) DO NOTHING",
                (bot, thread, kind),
            )


async def get_thread_bot_id(thread_id: Any, *, conn=None) -> Optional[str]:
    """The bot a thread carries, if any (None for a not-yet-stamped thread)."""
    cleaned = normalize_uuid(str(thread_id)) if thread_id else None
    if cleaned is None:
        return None
    async with get_db_connection(conn) as db:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT bot_id FROM conversation_threads "
                "WHERE conversation_thread_id = %s",
                (cleaned,),
            )
            row = await cur.fetchone()
            return str(row["bot_id"]) if row and row["bot_id"] else None


async def set_primary_thread(bot_id: Any, thread_id: Any, *, conn=None) -> None:
    """Pin the bot's private thread the first time one exists."""
    bot = _clean_bot_id(bot_id)
    thread = normalize_uuid(str(thread_id)) if thread_id else None
    if bot is None or thread is None:
        return
    async with get_db_connection(conn) as db:
        async with db.cursor() as cur:
            await cur.execute(
                "UPDATE bots SET primary_thread_id = COALESCE(primary_thread_id, %s), "
                "updated_at = NOW() WHERE bot_id = %s",
                (thread, bot),
            )
