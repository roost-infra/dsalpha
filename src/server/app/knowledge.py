"""Read-only HTTP access to the shared knowledge-base vault.

The vault is a directory of markdown notes that both athena and this app read;
``src/tools/knowledge_base`` owns the storage rules (path safety, frontmatter,
CJK-aware search ranking). The agent already reaches it through tools, but the
dashboard could not show any of it, so this exposes the same functions over
HTTP.

Reads only, deliberately. Writing goes through the agent's
``write_knowledge_note``, which titles, tags and cross-links as it writes — a
text box in a widget would produce notes that the agent's own retrieval ranks
badly.
"""

from __future__ import annotations

import logging
from collections import Counter

from fastapi import APIRouter, HTTPException, Query

from src.server.utils.api import CurrentUserId
from src.tools.knowledge_base.implementations import (
    VaultError,
    list_notes,
    read_note,
    search_notes,
    vault_root,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.get("/summary")
async def knowledge_summary(user_id: CurrentUserId) -> dict:
    """Note count, top-level folders and a rough size — the widget's header."""
    try:
        notes = list_notes(limit=500)
        root = vault_root()
    except VaultError as exc:
        # An unconfigured vault is a state, not a failure: the widget renders an
        # empty card rather than an error the user cannot act on.
        return {"configured": False, "reason": str(exc), "count": 0, "folders": []}

    folders: Counter[str] = Counter()
    for n in notes:
        path = n.get("path", "")
        folders[path.split("/", 1)[0] if "/" in path else "(根目录)"] += 1

    return {
        "configured": True,
        "root": root.name,
        "count": len(notes),
        "folders": [
            {"name": name, "count": count}
            for name, count in folders.most_common()
        ],
    }


@router.get("/notes")
async def knowledge_notes(
    user_id: CurrentUserId,
    folder: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """List notes, newest modification first."""
    try:
        notes = list_notes(folder=folder, limit=limit)
    except VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    notes.sort(key=lambda n: n.get("updated") or "", reverse=True)
    return {"notes": notes, "count": len(notes)}


@router.get("/notes/{path:path}")
async def knowledge_note(path: str, user_id: CurrentUserId) -> dict:
    """One note's text. ``path`` is vault-relative and resolved by the storage
    layer, which refuses anything that escapes the root."""
    try:
        note = read_note(path)
    except VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "path": note.path,
        "title": note.title,
        "text": note.text,
        "tags": list(note.tags),
        "updated": note.updated,
    }


@router.get("/search")
async def knowledge_search(
    user_id: CurrentUserId,
    q: str = Query(..., min_length=1, max_length=200),
    folder: str | None = Query(None, max_length=200),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Ranked search hits. The ranking is the storage layer's — path and title
    outrank tags, which outrank body — so the widget matches the agent's
    results for the same query."""
    try:
        hits = search_notes(q, limit=limit, folder=folder)
    except VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "query": q,
        "hits": [
            {
                "path": h.path,
                "title": h.title,
                "snippet": h.snippet,
                "tags": list(h.tags),
                "score": round(float(h.score), 3),
            }
            for h in hits
        ],
        "count": len(hits),
    }
