"""Content Desk page-plugin backend.

The desk is a user-owned JSON document plus a small, server-side operation
vocabulary. The UI writes through the same operations; revisions are optimistic,
so a stale tab gets a 409 instead of overwriting newer work. There is no second
AI entry here: the page hands AI work to the main Chat entry.
"""

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.server.database.pool import get_db_connection
from src.server.utils.api import CurrentUserId, handle_api_exceptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/content-desk", tags=["Content Desk"])

MAX_STATE_BYTES = 512_000
STATUSES = {"idea", "draft", "ready", "published"}
KINDS = {"note", "link", "quote", "topic", "clip"}
DEFAULT_STYLE = {
    "id": "style-default",
    "name": "我的默认风格",
    "tone": "直接、具体、有自己的判断",
    "audience": "刚开始理财的年轻人",
    "rules": "先说结论，再给理由；少用套话；每段只讲一件事。",
}


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "items": [],
        "metrics": [],
        "styles": [dict(DEFAULT_STYLE)],
        "activeStyleId": DEFAULT_STYLE["id"],
    }


def _clean_state(payload: Any) -> dict[str, Any]:
    state = _default_state()
    if not isinstance(payload, dict):
        return state
    for key in ("items", "metrics", "styles"):
        if isinstance(payload.get(key), list):
            state[key] = payload[key]
    if isinstance(payload.get("activeStyleId"), str):
        state["activeStyleId"] = payload["activeStyleId"]
    return state


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _find(state: dict[str, Any], key: str, item_id: Any) -> dict[str, Any]:
    row = next((row for row in state.get(key, []) if row.get("id") == item_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="找不到这条内容")
    return row


def apply_ops(state: dict[str, Any], ops: list[Any]) -> dict[str, Any]:
    """Apply the UI's operation vocabulary. Unknown fields and ops are dropped."""
    import copy
    import time

    next_state = copy.deepcopy(_clean_state(state))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for raw in ops[:40] if isinstance(ops, list) else []:
        if not isinstance(raw, dict):
            continue
        op = raw.get("op")
        if op == "add_item":
            title = _text(raw.get("title"), 120)
            if not title:
                continue
            item = {
                "id": _new_id("it"),
                "title": title,
                "body": _text(raw.get("body"), 60_000),
                "kind": raw.get("kind") if raw.get("kind") in KINDS else "note",
                "status": raw.get("status") if raw.get("status") in STATUSES else "idea",
                "platform": _text(raw.get("platform"), 40) or "小红书",
                "tags": [str(tag)[:32] for tag in (raw.get("tags") or [])][:12] if isinstance(raw.get("tags"), list) else [],
                "scheduledAt": _text(raw.get("scheduledAt"), 40) or None,
                "draft": raw.get("draft") if isinstance(raw.get("draft"), dict) else None,
                "createdAt": now,
                "updatedAt": now,
            }
            next_state["items"].insert(0, item)
        elif op == "update_item":
            item = _find(next_state, "items", raw.get("id"))
            for key, limit in (("title", 120), ("body", 60_000), ("platform", 40), ("scheduledAt", 40)):
                if key in raw:
                    value = _text(raw.get(key), limit)
                    item[key] = value or (None if key == "scheduledAt" else "")
            if "kind" in raw and raw["kind"] in KINDS:
                item["kind"] = raw["kind"]
            if "status" in raw and raw["status"] in STATUSES:
                item["status"] = raw["status"]
                item["publishedAt"] = now if raw["status"] == "published" else None
            if "tags" in raw and isinstance(raw["tags"], list):
                item["tags"] = [str(tag)[:32] for tag in raw["tags"]][:12]
            if isinstance(raw.get("draft"), dict):
                item["draft"] = raw["draft"]
            item["updatedAt"] = now
        elif op == "delete_item":
            before = len(next_state["items"])
            next_state["items"] = [i for i in next_state["items"] if i.get("id") != raw.get("id")]
            if len(next_state["items"]) == before:
                raise HTTPException(status_code=404, detail="找不到这条内容")
            next_state["metrics"] = [m for m in next_state["metrics"] if m.get("itemId") != raw.get("id")]
        elif op == "add_style":
            name = _text(raw.get("name"), 40)
            if not name:
                continue
            style = {
                "id": _new_id("st"),
                "name": name,
                "tone": _text(raw.get("tone"), 500),
                "audience": _text(raw.get("audience"), 500),
                "rules": _text(raw.get("rules"), 4000),
            }
            next_state["styles"].insert(0, style)
            next_state.setdefault("activeStyleId", style["id"])
        elif op == "set_active_style":
            if raw.get("id") is None or any(s.get("id") == raw.get("id") for s in next_state["styles"]):
                next_state["activeStyleId"] = raw.get("id")
        elif op == "add_metric":
            next_state["metrics"].insert(
                0,
                {
                    "id": _new_id("me"),
                    "itemId": raw.get("itemId") if isinstance(raw.get("itemId"), str) else None,
                    "platform": _text(raw.get("platform"), 40) or "小红书",
                    "date": _text(raw.get("date"), 10),
                    "views": max(0, int(raw.get("views") or 0)),
                    "likes": max(0, int(raw.get("likes") or 0)),
                    "comments": max(0, int(raw.get("comments") or 0)),
                    "saves": max(0, int(raw.get("saves") or 0)),
                },
            )
            next_state["metrics"] = next_state["metrics"][:500]
        elif op == "delete_metric":
            next_state["metrics"] = [m for m in next_state["metrics"] if m.get("id") != raw.get("id")]

    encoded = json.dumps(next_state, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="内容数据太大")
    return next_state


def _load_row(row: Optional[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    if row is None:
        return _default_state(), 0
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    return _clean_state(payload), int(row.get("revision") or 0)


async def _read(user_id: str) -> tuple[dict[str, Any], int]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT payload, revision FROM content_desk_states WHERE user_id = %s",
                (user_id,),
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    """
                    INSERT INTO content_desk_states (user_id, payload, revision, updated_at)
                    VALUES (%s, %s, 0, NOW())
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (user_id, Jsonb(_default_state())),
                )
                await conn.commit()
                return _default_state(), 0
            return _load_row(row)


async def _write(user_id: str, state: dict[str, Any], base_revision: int) -> int:
    encoded = json.dumps(state, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="内容数据太大")
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                UPDATE content_desk_states
                SET payload = %s, revision = revision + 1, updated_at = NOW()
                WHERE user_id = %s AND revision = %s
                RETURNING revision
                """,
                (Jsonb(state), user_id, base_revision),
            )
            row = await cur.fetchone()
            if row is None:
                await conn.rollback()
                raise HTTPException(status_code=409, detail="内容已被其他页面更新，请刷新后再试")
            await conn.commit()
            return int(row["revision"])


class OpsRequest(BaseModel):
    base_revision: int = Field(ge=0)
    ops: list[Any] = Field(default_factory=list)


@router.get("/state")
@handle_api_exceptions("read content desk", logger)
async def get_state(user_id: CurrentUserId):
    state, revision = await _read(user_id)
    return {"state": state, "revision": revision}


@router.post("/ops")
@handle_api_exceptions("write content desk", logger)
async def write_ops(req: OpsRequest, user_id: CurrentUserId):
    state, revision = await _read(user_id)
    if revision != req.base_revision:
        raise HTTPException(status_code=409, detail="内容已被其他页面更新，请刷新后再试")
    next_state = apply_ops(state, req.ops)
    next_revision = await _write(user_id, next_state, revision)
    return {"state": next_state, "revision": next_revision}
