"""Models for the built-in Bot market.

The catalogue is shipped with the build, not edited in the database, so these
models are both the validation boundary for ``services/bot_market/catalog.json``
and the response shapes the API serves. A template's persona and tool lists are
copied into a new Bot row on install; nothing here is a live Bot.
"""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

class BotTemplate(BaseModel):
    """The copyable half of a Bot: identity and its tool surface."""

    model_config = ConfigDict(extra="forbid")

    persona: str = Field(default="", max_length=20_000)
    model: Optional[str] = Field(default=None, max_length=128)
    skills: list[str] = Field(default_factory=list)
    tools_allow: list[str] = Field(min_length=1)
    tools_deny: list[str] = Field(default_factory=list)
    approval: Literal["ask", "edits", "auto", "full"] = "ask"
    memory_scopes: list[str] = Field(default_factory=lambda: ["workspace"])

    @field_validator("tools_allow", "tools_deny", "skills", "memory_scopes")
    @classmethod
    def _no_blank_entries(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("entries must not be blank")
        return cleaned


class CategoryLabels(BaseModel):
    """A category's display name in the shipped UI languages."""

    model_config = ConfigDict(extra="forbid")

    zh: str = Field(min_length=1, max_length=40)
    en: str = Field(min_length=1, max_length=40)


class CatalogCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    label: CategoryLabels


class CatalogBot(BaseModel):
    """One built-in Bot template as the build ships it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    name: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4_000)
    category: str
    tags: list[str] = Field(default_factory=list, max_length=8)
    icon: str = Field(default="🤖", max_length=8)
    featured: bool = False
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    template: BotTemplate


class BotMarketCatalog(BaseModel):
    """The whole shipped catalogue, validated once at load."""

    model_config = ConfigDict(extra="forbid")

    catalog_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    categories: list[CatalogCategory] = Field(min_length=1)
    bots: list[CatalogBot] = Field(min_length=1)

    @field_validator("bots")
    @classmethod
    def _unique_slugs(cls, bots: list[CatalogBot]) -> list[CatalogBot]:
        slugs = [bot.slug for bot in bots]
        if len(slugs) != len(set(slugs)):
            raise ValueError("bot slugs must be unique")
        return bots

    @field_validator("categories")
    @classmethod
    def _unique_categories(cls, categories: list[CatalogCategory]) -> list[CatalogCategory]:
        ids = [category.id for category in categories]
        if len(ids) != len(set(ids)):
            raise ValueError("category ids must be unique")
        return categories

    def model_post_init(self, __context: object) -> None:
        known = {category.id for category in self.categories}
        unknown = sorted({bot.category for bot in self.bots} - known)
        if unknown:
            raise ValueError(f"bots name unknown categories: {', '.join(unknown)}")


# --- API shapes -----------------------------------------------------------


class MarketCategory(BaseModel):
    """A filter chip, labelled for the caller's language."""

    id: str
    label: str


class MarketBotCard(BaseModel):
    """One card in the market grid."""

    slug: str
    name: str
    summary: str
    category: str
    tags: list[str]
    icon: str
    version: str
    featured: bool
    installed: bool


class MarketBotList(BaseModel):
    bots: list[MarketBotCard]
    categories: list[MarketCategory]


class MarketInstallLocation(BaseModel):
    """One place this user installed a template (for the detail page)."""

    install_id: str
    workspace_id: str
    workspace_name: str
    bot_id: str
    bot_name: str


class MarketBotDetail(BaseModel):
    """The full listing; the persona is readable because the market is free."""

    slug: str
    name: str
    summary: str
    description: str
    category: str
    tags: list[str]
    icon: str
    version: str
    featured: bool
    persona: str
    tools: list[str]
    skills: list[str]
    installs: list[MarketInstallLocation]


class MarketInstallRequest(BaseModel):
    """Install into one of the caller's workspaces."""

    workspace_id: uuid.UUID
    name: Optional[str] = Field(default=None, max_length=64)


class MarketInstalledBot(BaseModel):
    bot_id: str
    name: str
    workspace_id: str


class MarketInstallResponse(BaseModel):
    install_id: str
    bot: MarketInstalledBot


class MarketInstallRecord(BaseModel):
    """A row of the caller's install journal."""

    install_id: str
    slug: str
    name: str
    version: str
    workspace_id: str
    workspace_name: str
    bot_id: str
    bot_name: str
    created_at: str


class MarketInstallList(BaseModel):
    installs: list[MarketInstallRecord]
