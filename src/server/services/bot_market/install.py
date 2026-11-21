"""Install a built-in Bot template into one of the caller's workspaces.

Installing is a copy, not a share: the new Bot row belongs to the buyer, names
their workspace, and carries the template's persona and tool lists. The
template is never referenced afterwards, so an author updating the catalogue
does not rewrite copies already installed.

The catalogue is free and there are no entitlements to check. What can go
wrong is the workspace's own limits: the 20-Bot cap, a name already taken, and
the Home workspace (where the derived Chief of Staff runs).
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional

from src.server.database import bot_market as market_db
from src.server.database import bots as bot_db
from src.server.models.bot_market import CatalogBot

logger = logging.getLogger(__name__)

#: The longest Bot name the bots table accepts (the API's BotCreate limit).
MAX_NAME_LENGTH = 64
#: How many suffixed names an install tries before giving up. The page can ask
#: the user to rename, so this only needs to cover a few collisions.
MAX_NAME_ATTEMPTS = 6


class TemplateNotFound(Exception):
    """The build does not ship a Bot template under that slug."""


class WorkspaceFull(Exception):
    """The workspace already holds the maximum number of Bots."""


class NameTaken(Exception):
    """Every candidate name is taken in the workspace."""


def _candidates(base: str) -> Iterator[str]:
    """``base``, then ``base 2`` … within the name limit.

    Suffixing keeps a one-click install working when the obvious name is
    taken; when even the last candidate is taken the caller gets
    :class:`NameTaken` and can rename in the UI.
    """
    base = (base or "").strip() or "Bot"
    for attempt in range(1, MAX_NAME_ATTEMPTS + 1):
        suffix = "" if attempt == 1 else f" {attempt}"
        room = MAX_NAME_LENGTH - len(suffix)
        yield f"{base[:room]}{suffix}"


async def install_bot(
    *,
    user_id: str,
    bot: CatalogBot,
    workspace_id: str,
    name: Optional[str] = None,
) -> tuple[dict, dict]:
    """Create the Bot and record where it came from.

    Returns ``(install_row, bot_row)``. A taken name is retried with a suffix;
    a full workspace raises :class:`WorkspaceFull`. The Bot is created first
    because the install journal needs its id; if recording the journal fails,
    the exception propagates and the Bot row simply has no journal entry
    (the installs page is history, not authority).
    """
    requested = (name or bot.name).strip() or bot.name
    for candidate in _candidates(requested):
        try:
            row = await bot_db.create_bot(
                user_id,
                workspace_id,
                candidate,
                role="analyst",
                persona=bot.template.persona,
                avatar={},
                provider=None,
                model=bot.template.model,
                skills=bot.template.skills,
                tools_allow=bot.template.tools_allow,
                tools_deny=bot.template.tools_deny,
                approval=bot.template.approval,
                memory_scopes=bot.template.memory_scopes,
                created_by=user_id,
            )
        except bot_db.BotNameTaken:
            continue
        except ValueError as exc:
            raise WorkspaceFull(str(exc)) from None
        install = await market_db.record_install(
            user_id=user_id,
            slug=bot.slug,
            version=bot.version,
            workspace_id=workspace_id,
            bot_id=str(row["bot_id"]),
        )
        logger.info(
            "bot_market.install | user=%s slug=%s version=%s bot=%s install=%s",
            user_id,
            bot.slug,
            bot.version,
            row.get("bot_id"),
            install.get("install_id"),
        )
        return install, row
    raise NameTaken(requested)
