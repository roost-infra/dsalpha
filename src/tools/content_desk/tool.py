"""A single main-Agent tool for the user's Content Desk page.

The page has its own persisted state and op vocabulary; this tool only adapts
the same operations for a chat turn. It is deliberately one tool, not another
assistant: the model uses the normal conversation and this handle, so there is
one thread, one model setting and one set of skills.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.server.app.content_desk import _read, _write, apply_ops
from src.server.database.page_plugins import list_user_page_plugins

logger = logging.getLogger(__name__)

STATUSES = {"idea", "draft", "ready", "published"}
KINDS = {"note", "link", "quote", "topic", "clip"}
PLATFORMS = ["公众号", "小红书", "抖音", "B站", "视频号", "X", "TikTok", "Instagram", "YouTube"]


class ContentDeskArgs(BaseModel):
    action: Literal[
        "list", "get", "add", "update", "delete", "schedule", "set_status", "save_draft", "add_style"
    ] = Field(description="The operation to perform.")
    item_id: Optional[str] = Field(default=None, description="Content item id for get/update/delete/schedule/set_status/save_draft.")
    title: Optional[str] = Field(default=None, description="Title for add/update.")
    body: Optional[str] = Field(default=None, description="Notes or draft body for add/update.")
    kind: Optional[Literal["note", "link", "quote", "topic", "clip"]] = Field(default=None, description="Item kind.")
    platform: Optional[str] = Field(default=None, description=f"Publishing platform: {', '.join(PLATFORMS)}.")
    tags: Optional[list[str]] = Field(default=None, description="Tags for add/update.")
    status: Optional[Literal["idea", "draft", "ready", "published"]] = Field(default=None, description="Lifecycle status.")
    scheduled_at: Optional[str] = Field(default=None, description="ISO-8601 date/time to schedule, or null to clear.")
    text: Optional[str] = Field(default=None, description="Draft body for save_draft.")
    style_name: Optional[str] = Field(default=None, description="Style name for add_style.")


def _user_id(config: RunnableConfig) -> Optional[str]:
    return ((config or {}).get("configurable") or {}).get("user_id")


async def _enabled(user_id: str) -> bool:
    try:
        rows = await list_user_page_plugins(user_id)
    except Exception:
        logger.warning("[content_desk] page-plugin check failed", exc_info=True)
        return True
    return any(row.get("plugin_id") == "content-desk" and row.get("enabled") for row in rows)


def _line(item: dict) -> str:
    scheduled = f" · {item['scheduledAt'][:10]}" if item.get("scheduledAt") else ""
    return f"- {item['id']} · {item.get('status', 'idea')} · {item.get('title', '')}{scheduled}"


def _summary(state: dict) -> str:
    items = state.get("items") or []
    if not items:
        return "The Content Desk has no items yet."
    lines = "\n".join(_line(row) for row in items[:30])
    more = f"\n… and {len(items) - 30} more" if len(items) > 30 else ""
    return f"Content Desk items ({len(items)}):\n{lines}{more}"


def _detail(item: dict) -> str:
    parts = [f"{item.get('title', '')} ({item.get('id')})", f"status: {item.get('status')}"]
    if item.get("platform"):
        parts.append(f"platform: {item['platform']}")
    if item.get("scheduledAt"):
        parts.append(f"scheduled: {item['scheduledAt']}")
    if item.get("tags"):
        parts.append(f"tags: {', '.join(item['tags'])}")
    if item.get("body"):
        parts.append(f"notes: {item['body']}")
    if item.get("draft"):
        parts.append(f"draft: {str(item['draft'])[:3000]}")
    return "\n".join(parts)


def _build_ops(args: ContentDeskArgs) -> list[dict]:
    if args.action == "add":
        op = {"op": "add_item"}
        for key, value in (
            ("title", args.title), ("body", args.body), ("kind", args.kind),
            ("platform", args.platform), ("tags", args.tags), ("status", args.status),
        ):
            if value is not None:
                op[key] = value
        return [op]
    if args.action == "update":
        if not args.item_id:
            raise ValueError("item_id is required for update")
        op = {"op": "update_item", "id": args.item_id}
        for key, value in (
            ("title", args.title), ("body", args.body), ("kind", args.kind),
            ("platform", args.platform), ("tags", args.tags), ("status", args.status),
            ("scheduledAt", args.scheduled_at),
        ):
            if value is not None:
                op[key] = value
        return [op]
    if args.action == "delete":
        if not args.item_id:
            raise ValueError("item_id is required for delete")
        return [{"op": "delete_item", "id": args.item_id}]
    if args.action == "schedule":
        if not args.item_id:
            raise ValueError("item_id is required for schedule")
        return [{"op": "update_item", "id": args.item_id, "scheduledAt": args.scheduled_at}]
    if args.action == "set_status":
        if not args.item_id:
            raise ValueError("item_id is required for set_status")
        return [{"op": "update_item", "id": args.item_id, "status": args.status}]
    if args.action == "save_draft":
        if not args.item_id or args.text is None:
            raise ValueError("item_id and text are required for save_draft")
        return [{"op": "update_item", "id": args.item_id, "draft": {"body": args.text, "model": "LangAlpha"}, "status": "draft"}]
    if args.action == "add_style":
        if not args.style_name:
            raise ValueError("style_name is required for add_style")
        return [{"op": "add_style", "name": args.style_name}]
    raise ValueError("unsupported action")


@tool("content_desk", args_schema=ContentDeskArgs)
async def content_desk(
    action: Literal["list", "get", "add", "update", "delete", "schedule", "set_status", "save_draft", "add_style"],
    config: RunnableConfig,
    item_id: Optional[str] = None,
    title: Optional[str] = None,
    body: Optional[str] = None,
    kind: Optional[str] = None,
    platform: Optional[str] = None,
    tags: Optional[list[str]] = None,
    status: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    text: Optional[str] = None,
    style_name: Optional[str] = None,
) -> str:
    """Read or edit the user's Content Desk: ideas, drafts, scheduled posts and
    writing styles. Use it when the user asks about their content workbench,
    wants a topic added or changed, wants a draft saved, or wants a post
    scheduled — no separate content assistant exists.

    The page is a distinct surface: this is the only way to change it from chat.
    Every write is optimistic. ``add`` returns an id; pass it to later calls.

    Args:
        action: list, get, add, update, delete, schedule, set_status, save_draft or add_style.
        item_id: Content id for get/update/delete/schedule/set_status/save_draft.
        title: Title for add/update.
        body: Notes for add/update.
        kind: note, link, quote, topic or clip.
        platform: Publishing platform, e.g. 小红书, 公众号, 抖音.
        tags: Tags for add/update.
        status: idea, draft, ready or published.
        scheduled_at: ISO-8601 date/time; null clears the schedule.
        text: Draft body for save_draft.
        style_name: Style name for add_style.

    Returns:
        A short list, one item in detail, or a confirmation and the new state summary.
    """
    user_id = _user_id(config)
    if not user_id:
        return "No user context for Content Desk."
    if not await _enabled(str(user_id)):
        return "Content Desk is disabled. Ask the user to enable it on Plugins → 内置页面插件 → 内容工作台."
    args = ContentDeskArgs(
        action=action, item_id=item_id, title=title, body=body, kind=kind,
        platform=platform, tags=tags, status=status, scheduled_at=scheduled_at,
        text=text, style_name=style_name,
    )
    state, revision = await _read(str(user_id))
    if action == "list":
        return _summary(state)
    if action == "get":
        if not item_id:
            return "item_id is required for get."
        item = next((row for row in state.get("items", []) if row.get("id") == item_id), None)
        return _detail(item) if item else f"No Content Desk item with id {item_id}."
    try:
        ops = _build_ops(args)
    except ValueError as exc:
        return str(exc)
    try:
        next_state = apply_ops(state, ops)
        next_revision = await _write(str(user_id), next_state, revision)
    except Exception as exc:
        return f"Content Desk write failed: {exc}"
    return f"Done (revision {next_revision}).\n{_summary(next_state)}"


CONTENT_DESK_TOOLS = [content_desk]
