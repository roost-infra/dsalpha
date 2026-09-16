"""Knowledge-base tools: read and write athena's shared markdown vault.

The vault is the durable half of a research loop — an analysis that ends up
only in the thread dies with the thread. These four tools are what makes a
finding outlive the conversation, so the docstrings spend their words on
routing: search before reading, read before writing, and write only what a
future session would need.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from src.tools.knowledge_base.implementations import (
    VaultError,
    list_notes,
    read_note,
    search_notes,
    write_note,
)

__all__ = [
    "search_knowledge_base",
    "read_knowledge_note",
    "write_knowledge_note",
    "list_knowledge_notes",
    "knowledge_base_tools",
]


def _fail(exc: Exception) -> str:
    return f"Knowledge base error: {exc}"


@tool
async def search_knowledge_base(
    query: str, limit: int = 8, folder: str | None = None
) -> str:
    """Search the shared knowledge base (prior research notes, 复盘, 产业链).

    Use this before researching something the user may already have covered,
    and before writing a note — an existing note should be updated, not
    duplicated. Ranking favours filename and title matches over body matches.

    Args:
        query: Keywords, a company name, a ticker, or a phrase. Chinese and
            English both work; partial CJK matches are matched on bigrams.
        limit: Maximum hits to return, 1-50 (default 8).
        folder: Restrict to a subfolder of the vault, e.g. "复盘" or "wiki".
            Omit to search the whole vault.

    Returns:
        Ranked hits (path, score, snippet) — paths are what read_knowledge_note
        takes, so this is a lookup step rather than the answer.
    """
    try:
        hits = search_notes(query, limit=limit, folder=folder)
    except VaultError as exc:
        return _fail(exc)
    if not hits:
        return f"No knowledge-base notes matched {query!r}."
    lines = [f"{len(hits)} note(s) matched {query!r}:"]
    for h in hits:
        tag = f"  [{', '.join(h.tags)}]" if h.tags else ""
        lines.append(f"\n- {h.path}  (score {h.score}){tag}\n  {h.title}\n  …{h.snippet}…")
    return "\n".join(lines)


@tool
async def read_knowledge_note(path: str) -> str:
    """Read one knowledge-base note in full, by the path search returned.

    Args:
        path: Vault-relative path, e.g. "产业链/光模块.md". A missing .md
            suffix is added; paths outside the vault are refused.

    Returns:
        The note body plus its frontmatter — the full text, so prefer this over
        guessing at content from a search snippet.
    """
    try:
        note = read_note(path)
    except VaultError as exc:
        return _fail(exc)
    fm = ", ".join(f"{k}={v}" for k, v in note.frontmatter.items()) or "(none)"
    return (
        f"# {note.title}\n"
        f"path: {note.path}\nupdated: {note.updated}\nfrontmatter: {fm}\n\n"
        f"{note.text}"
    )


@tool
async def write_knowledge_note(
    path: str,
    content: str,
    tags: list[str] | None = None,
    mode: str = "overwrite",
) -> str:
    """Create or update a knowledge-base note — how a finding outlives the thread.

    Write when the user asks to save/记录 something, or when a conclusion would
    be worth re-reading in a later session. Search first: updating the note that
    exists beats adding a near-duplicate beside it.

    Args:
        path: Vault-relative path, e.g. "复盘/2026-09-16 光模块.md". Parent
            folders are created; a missing .md suffix is added.
        content: Markdown body. Frontmatter (title/created/updated/tags) is
            generated for you — do not write it yourself.
        tags: Optional tags stored in frontmatter; omitted tags are preserved
            on an existing note.
        mode: "overwrite" (default), "append", or "prepend". Use append to add
            to a running log such as a 复盘 note.

    Returns:
        The written path and whether the note was created or updated.
    """
    try:
        result: dict[str, Any] = write_note(
            path, content, tags=list(tags) if tags else None, mode=mode
        )
    except VaultError as exc:
        return _fail(exc)
    verb = "Created" if result["created"] else "Updated"
    return f"{verb} {result['path']} ({result['mode']}, {result['words']} chars)."


@tool
async def list_knowledge_notes(folder: str | None = None, limit: int = 100) -> str:
    """List what the knowledge base holds, newest-modified first is not guaranteed.

    Use to get oriented before searching — it answers "what has this desk
    already written about" without guessing at query words.

    Args:
        folder: Restrict to a subfolder; omit to list the whole vault.
        limit: Maximum notes to list, 1-500 (default 100).

    Returns:
        One line per note (path, last modified) — paths feed read_knowledge_note.
    """
    try:
        notes = list_notes(folder=folder, limit=limit)
    except VaultError as exc:
        return _fail(exc)
    if not notes:
        return "The knowledge base has no notes" + (f" under {folder!r}." if folder else ".")
    lines = [f"{len(notes)} note(s):"]
    lines += [f"- {n['path']}  (updated {n['updated']})" for n in notes]
    return "\n".join(lines)


def knowledge_base_tools() -> list[Any]:
    """The four vault tools, for the agent's direct-tool list."""
    return [
        search_knowledge_base,
        read_knowledge_note,
        write_knowledge_note,
        list_knowledge_notes,
    ]
