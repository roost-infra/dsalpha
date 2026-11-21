"""A bot's tool surface: the whole set unless it narrowed it.

``tools_allow`` is a whitelist (empty means "everything"), ``tools_deny`` a
blacklist applied after it. The filter runs on the built main-agent tools, so
a name it removes is invisible to the model rather than refused at call time.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


def tool_names(tools: Iterable[Any]) -> list[str]:
    return [str(getattr(tool, "name", "") or "") for tool in tools]


#: Composio names a tool after its toolkit: ``GITHUB_CREATE_AN_ISSUE``,
#: ``GMAIL_SEND_EMAIL``. The grant keys are toolkit slugs, so this map is what
#: lets an app-level grant filter the flat MCP tool list. A tool no prefix
#: claims is not a connector tool and is never filtered here.
_CONNECTOR_PREFIXES: dict[str, tuple[str, ...]] = {
    "github": ("GITHUB_",),
    "gmail": ("GMAIL_",),
    "googlecalendar": ("GOOGLECALENDAR_", "GOOGLE_CALENDAR_"),
    "googlesheets": ("GOOGLESHEETS_", "GOOGLE_SHEETS_"),
    "googledocs": ("GOOGLEDOCS_", "GOOGLE_DOCS_"),
    "googledrive": ("GOOGLEDRIVE_", "GOOGLE_DRIVE_"),
    "slack": ("SLACK_",),
    "notion": ("NOTION_",),
    "linear": ("LINEAR_",),
    "sentry": ("SENTRY_",),
    "discord": ("DISCORD_",),
    "twitter": ("TWITTER_", "X_"),
    "reddit": ("REDDIT_",),
    "jira": ("JIRA_",),
    "asana": ("ASANA_",),
    "trello": ("TRELLO_",),
    "airtable": ("AIRTABLE_",),
    "dropbox": ("DROPBOX_",),
    "stripe": ("STRIPE_",),
    "zoom": ("ZOOM_",),
    "telegram": ("TELEGRAM_",),
    "outlook": ("OUTLOOK_",),
    "microsoftteams": ("MICROSOFTTEAMS_", "MICROSOFT_TEAMS_"),
    "figma": ("FIGMA_",),
    "clickup": ("CLICKUP_",),
}


def connector_app(tool_name: str) -> str | None:
    """The connected-app slug a Composio tool belongs to, when one knows it."""
    upper = (tool_name or "").upper()
    for slug, prefixes in _CONNECTOR_PREFIXES.items():
        if any(upper.startswith(prefix) for prefix in prefixes):
            return slug
    return None


def _grant_allows(tool_name: str, grants: dict[str, Any]) -> bool:
    """Whether a per-bot connector grant admits this tool.

    An empty grant map means unrestricted. Once it names any app, a tool from
    an app it does not name is refused; a named app admits everything for
    ``tools: "*"`` or only the listed tool names.
    """
    if not grants:
        return True
    app = connector_app(tool_name)
    if app is None:
        return True
    grant = grants.get(app)
    if not isinstance(grant, dict):
        return False
    tools = grant.get("tools")
    if tools == "*":
        return True
    return isinstance(tools, list) and tool_name in tools


def narrow_tools(tools: list[Any], bot: Optional[dict]) -> list[Any]:
    """Apply a bot's allow/deny lists to the main agent's tools.

    A bot with no lists keeps the whole set; a bot with an allow list keeps
    only those names; deny always wins over allow, and names the build never
    bound are ignored (a plugin may have been uninstalled since).
    """
    if not bot:
        return tools
    allow = {str(name) for name in (bot.get("tools_allow") or []) if name}
    deny = {str(name) for name in (bot.get("tools_deny") or []) if name}
    grants = bot.get("connector_tools") or {}
    if not allow and not deny and not grants:
        return tools
    kept = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        if allow and name not in allow:
            continue
        if name in deny:
            continue
        if not _grant_allows(name, grants):
            continue
        kept.append(tool)
    return kept
