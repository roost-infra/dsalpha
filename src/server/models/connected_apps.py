"""Models for the Connected apps page.

A user connects external accounts through Composio; the page lists the
marketplace, the accounts already connected, and the OAuth link a Connect
button opens. Nothing here ever carries a credential.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ConnectedAccount(BaseModel):
    id: str
    alias: Optional[str] = None
    status: str


class ConnectedApp(BaseModel):
    slug: str
    name: str
    description: str = ""
    logo: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
    connected: bool = False
    accounts: list[ConnectedAccount] = Field(default_factory=list)


class ConnectedAppsStatus(BaseModel):
    """What the page needs in one answer.

    ``configured`` is false until a usable Composio project key exists;
    ``using_deployment_key`` says the key came from the deployment rather than
    the user's vault, which only changes the setup copy.
    """

    configured: bool
    using_deployment_key: bool = False
    apps: list[ConnectedApp] = Field(default_factory=list)
    error: Optional[str] = None


class ConnectedAppKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=256)


class ConnectRequest(BaseModel):
    alias: Optional[str] = Field(default=None, max_length=64)


class ConnectLink(BaseModel):
    url: str
