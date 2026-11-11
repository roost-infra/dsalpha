"""The user's switches for built-in page plugins.

The manifests live in the web app; this API answers which of this build's
known plugin ids the caller has enabled and records a switch. It is not a
plugin installation API: page plugin code ships with the app and cannot be
uploaded here.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.server.database.page_plugins import (
    PAGE_PLUGIN_IDS,
    list_user_page_plugins,
    set_user_page_plugin,
)
from src.server.utils.api import CurrentUserId, handle_api_exceptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/page-plugins", tags=["Page plugins"])


class PagePlugin(BaseModel):
    plugin_id: str
    enabled: bool


class PagePluginsResponse(BaseModel):
    plugins: List[PagePlugin]


class PagePluginUpdate(BaseModel):
    enabled: bool


def _known(plugin_id: str) -> bool:
    return plugin_id in PAGE_PLUGIN_IDS


@router.get("", response_model=PagePluginsResponse)
@handle_api_exceptions("list page plugins", logger)
async def list_page_plugins(user_id: CurrentUserId):
    rows = {row["plugin_id"]: bool(row.get("enabled")) for row in await list_user_page_plugins(user_id)}
    # Every known id is returned, including the unset ones, so the client can
    # render the catalogue without another manifest call.
    return PagePluginsResponse(
        plugins=[
            PagePlugin(plugin_id=plugin_id, enabled=rows.get(plugin_id, False))
            for plugin_id in PAGE_PLUGIN_IDS
        ]
    )


@router.patch("/{plugin_id}", response_model=PagePlugin)
@handle_api_exceptions("update page plugin", logger)
async def update_page_plugin(
    plugin_id: str, body: PagePluginUpdate, user_id: CurrentUserId
):
    if not _known(plugin_id):
        raise HTTPException(status_code=404, detail="unknown page plugin")
    row = await set_user_page_plugin(user_id, plugin_id, body.enabled)
    return PagePlugin(plugin_id=row["plugin_id"], enabled=bool(row.get("enabled")))
