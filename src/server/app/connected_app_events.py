"""Composio trigger webhooks that start connector automations.

Composio delivers one connected-app event at a time. The webhook names the
Composio user, the app and the event; this router maps that user to its
installation, finds active automations whose ``connector`` trigger matches,
and dispatches each run through the existing AutomationScheduler so a run's
thread, delivery and failure trail are the same as a scheduled one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.config.env import COMPOSIO_WEBHOOK_SECRET
from src.server.database import automation as auto_db
from src.server.database import automation_executions as exec_db
from src.server.database import connected_apps as installation_db
from src.server.services.automation_scheduler import AutomationScheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/connected-apps", tags=["Connected apps"])


class ConnectorEventBody(BaseModel):
    """The subset of a Composio trigger delivery that starts a run."""

    user_id: str = Field(..., min_length=1, max_length=255)
    app: str = Field(..., min_length=1, max_length=64)
    event: str = Field(..., min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("app")
    @classmethod
    def _app_slug(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("app is required")
        return cleaned

    @field_validator("event")
    @classmethod
    def _event_name(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("event is required")
        return cleaned


def _matches(filters: Any, payload: dict[str, Any]) -> bool:
    if not isinstance(filters, dict) or not filters:
        return True
    return all(payload.get(key) == value for key, value in filters.items())


@router.post("/events")
async def receive_connector_event(
    body: ConnectorEventBody,
    x_composio_webhook_secret: str | None = Header(default=None),
) -> dict[str, int]:
    """Accept one Composio trigger delivery and dispatch matching automations."""
    if not COMPOSIO_WEBHOOK_SECRET or x_composio_webhook_secret != COMPOSIO_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    installation = await installation_db.get_installation_by_composio_user(body.user_id)
    if installation is None:
        # A stale or unrelated project delivery: acknowledge it so Composio
        # does not retry forever, but start nothing.
        return {"matched": 0}

    rows = await auto_db.list_connector_automations(
        installation["user_id"], body.app, body.event
    )
    matched = 0
    scheduler = AutomationScheduler.get_instance()
    now = datetime.now(timezone.utc)
    for row in rows:
        config = row.get("trigger_config") or {}
        if not _matches(config.get("filters"), body.payload):
            continue
        execution_id = await exec_db.create_execution(
            str(row["automation_id"]), now, scheduler.server_id
        )
        automation = dict(row)
        automation["additional_context"] = [
            *(automation.get("additional_context") or []),
            {
                "type": "connected_app_event",
                "app": body.app,
                "event": body.event,
                "payload": body.payload,
            },
        ]
        scheduler.dispatch(
            automation,
            execution_id,
            name=f"automation_connector_{str(row['automation_id'])[:8]}",
        )
        matched += 1
    logger.info(
        "[CONNECTED-APPS] connector event app=%s event=%s user=%s matched=%s",
        body.app,
        body.event,
        installation["user_id"],
        matched,
    )
    return {"matched": matched}
