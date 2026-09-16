"""Knowledge-base storage over a markdown vault (athena's ``~/quant-vault``).

File-backed on purpose: the vault on disk is the artifact athena and LangAlpha
both read, so sharing it needs no database coupling and no migration. A note is
a ``.md`` file, optionally opened by a YAML-ish frontmatter block.

Search is a plain substring/term rank rather than an index. The vault is small
(hundreds of notes), CJK queries have no whitespace to tokenise on, and an
index would have to be invalidated by whoever else writes a note — which is
exactly the property that makes a shared directory useful.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

__all__ = [
    "VaultError",
    "NoteRef",
    "Note",
    "vault_root",
    "search_notes",
    "read_note",
    "write_note",
    "list_notes",
]

# Frontmatter is ``---\n...\n---`` at the very top of the file.
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


class VaultError(ValueError):
    """A call that cannot be served — bad path, missing note, no vault."""


@dataclass(frozen=True)
class NoteRef:
    """A search hit: enough to decide whether to spend a second call reading it."""

    path: str
    title: str
    score: float
    snippet: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Note:
    path: str
    title: str
    text: str
    frontmatter: dict[str, str] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    updated: str = ""


def vault_root() -> Path:
    """The vault directory, or raise if the deployment has no readable one.

    ``ATHENA_VAULT_ROOT`` wins so a container can point at a mount; otherwise
    the conventional home-directory vault, which is what the desktop installs
    have. Both are checked for existence so the failure names the problem
    instead of surfacing as an empty result set.
    """
    candidates: list[Path] = []
    env = os.environ.get("ATHENA_VAULT_ROOT")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path.home() / "quant-vault")
    candidates.append(Path.home() / "Obsidian Vault")

    for c in candidates:
        if c.is_dir():
            return c
    raise VaultError(
        "no knowledge-base vault found; set ATHENA_VAULT_ROOT to a directory "
        f"(checked: {', '.join(str(c) for c in candidates)})"
    )


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Split leading frontmatter from body. Values stay strings — nothing here
    needs the types, and a YAML dependency would be a poor trade for them."""
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        meta[key.strip()] = value.strip().strip("'\"")
    # The blank line separating frontmatter from body is not body content;
    # leaving it on makes every append accumulate leading newlines.
    return meta, raw[m.end() :].lstrip("\r\n")


def _tags_of(meta: dict[str, str]) -> tuple[str, ...]:
    for key in ("tags", "tag", "keywords"):
        if key in meta:
            return tuple(
                t.strip().strip("'\"[]")
                for t in re.split(r"[,\s]+", meta[key])
                if t.strip().strip("'\"[]")
            )
    return ()


def _title_of(meta: dict[str, str], body: str, path: Path) -> str:
    if meta.get("title"):
        return meta["title"]
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _resolve(value: str) -> tuple[Path, str]:
    """Map a caller-supplied note path onto the vault, refusing escapes.

    The agent writes this string, so ``../`` and absolute paths are the two
    ways it could reach outside the vault; both are rejected rather than
    normalised, because a silently-rewritten path is a note filed somewhere
    nobody will look for it.
    """
    root = vault_root()
    candidate = Path(value)
    if candidate.is_absolute():
        raise VaultError("path must be relative to the knowledge-base root")
    if any(part == ".." for part in candidate.parts):
        raise VaultError("path must not contain '..'")
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    rel = candidate.as_posix()
    full = (root / candidate).resolve()
    if not str(full).startswith(str(root.resolve())):
        raise VaultError("path escapes the knowledge-base root")
    return full, rel


def _iter_notes(root: Path, folder: str | None = None):
    base = root if not folder else (root / folder)
    if not base.is_dir():
        raise VaultError(f"no such folder in the knowledge base: {folder}")
    for p in sorted(base.rglob("*.md")):
        if p.name.startswith("."):
            continue
        yield p


def _snippet(body: str, needles: list[str], width: int = 160) -> str:
    """The window around the first hit, so the line that matched is visible."""
    flat = body.replace("\r", "")
    low = flat.lower()
    pos = -1
    for n in needles:
        pos = low.find(n.lower())
        if pos >= 0:
            break
    if pos < 0:
        return flat[:width].replace("\n", " ").strip()
    start = max(0, pos - width // 3)
    return flat[start : start + width].replace("\n", " ").strip()


def _terms(query: str) -> list[str]:
    """Query as search needles.

    Latin words split on whitespace/punctuation; a CJK run has no such
    separators, so the whole run stays one needle and the character bigrams
    below carry the partial-match case.
    """
    parts = [t for t in re.split(r"[\s,，、;；/|]+", query.strip()) if t]
    needles: list[str] = []
    for p in parts:
        needles.append(p)
        if len(p) > 2 and any("\u4e00" <= ch <= "\u9fff" for ch in p):
            needles.extend(p[i : i + 2] for i in range(len(p) - 1))
    return needles or [query.strip()]


def search_notes(
    query: str, limit: int = 8, folder: str | None = None
) -> list[NoteRef]:
    """Rank notes by where the query hits: path/title outrank tags outrank body."""
    if not query or not query.strip():
        raise VaultError("query must not be empty")
    limit = max(1, min(int(limit), 50))
    root = vault_root()
    needles = [n.lower() for n in _terms(query)]

    hits: list[NoteRef] = []
    for path in _iter_notes(root, folder):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = _parse_frontmatter(raw)
        title = _title_of(meta, body, path)
        rel = path.relative_to(root).as_posix()
        tags = _tags_of(meta)

        hay_path = f"{rel} {title}".lower()
        hay_tags = " ".join(tags).lower()
        hay_body = body.lower()

        score = 0.0
        for n in needles:
            if n in hay_path:
                score += 5.0
            if n in hay_tags:
                score += 3.0
            score += hay_body.count(n) * 1.0
        if score <= 0:
            continue
        hits.append(
            NoteRef(
                path=rel,
                title=title,
                score=round(score, 2),
                snippet=_snippet(body, needles),
                tags=tags,
            )
        )

    hits.sort(key=lambda h: (-h.score, h.path))
    return hits[:limit]


def read_note(path: str) -> Note:
    full, rel = _resolve(path)
    if not full.is_file():
        raise VaultError(f"no such note: {rel}")
    raw = full.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_frontmatter(raw)
    return Note(
        path=rel,
        title=_title_of(meta, body, full),
        text=body,
        frontmatter=meta,
        tags=_tags_of(meta),
        updated=datetime.fromtimestamp(full.stat().st_mtime).isoformat(timespec="seconds"),
    )


def write_note(
    path: str,
    content: str,
    *,
    tags: list[str] | None = None,
    mode: str = "overwrite",
) -> dict[str, object]:
    """Create or update a note, stamping frontmatter so the vault stays uniform."""
    if not content or not content.strip():
        raise VaultError("content must not be empty")
    mode = (mode or "overwrite").lower()
    if mode not in ("overwrite", "append", "prepend"):
        raise VaultError("mode must be one of: overwrite, append, prepend")

    full, rel = _resolve(path)
    full.parent.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()

    existed = full.is_file()
    previous = full.read_text(encoding="utf-8", errors="replace") if existed else ""
    prev_meta, prev_body = _parse_frontmatter(previous)
    if tags is None:
        tags = list(_tags_of(prev_meta))

    title = prev_meta.get("title") or Path(rel).stem
    created = prev_meta.get("created") or stamp
    fm = [f"title: {title}", f"created: {created}", f"updated: {stamp}"]
    if tags:
        fm.append("tags: [" + ", ".join(tags) + "]")

    if mode == "append" and prev_body.strip():
        body = prev_body.rstrip() + "\n\n" + content.strip() + "\n"
    elif mode == "prepend" and prev_body.strip():
        body = content.strip() + "\n\n" + prev_body.lstrip()
    else:
        body = content.strip() + "\n"

    full.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + body, encoding="utf-8")
    return {
        "path": rel,
        "created": not existed,
        "mode": mode,
        "updated": stamp,
        "words": len(body),
    }


def list_notes(folder: str | None = None, limit: int = 100) -> list[dict[str, str]]:
    root = vault_root()
    limit = max(1, min(int(limit), 500))
    out: list[dict[str, str]] = []
    for path in _iter_notes(root, folder):
        rel = path.relative_to(root).as_posix()
        meta, body = _parse_frontmatter(
            path.read_text(encoding="utf-8", errors="replace")
        )
        out.append(
            {
                "path": rel,
                "title": _title_of(meta, body, path),
                "updated": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat(timespec="seconds"),
            }
        )
        if len(out) >= limit:
            break
    return out
