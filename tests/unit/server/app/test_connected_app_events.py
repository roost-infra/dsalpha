"""Composio trigger webhooks dispatch the automations that watch the event."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.server.app import connected_app_events as events


def _body(**overrides):
    values = {
        "user_id": "dsalpha_1",
        "app": "github",
        "event": "GITHUB_ISSUE_CREATED",
        "payload": {"title": "Broken", "number": 7},
    }
    values.update(overrides)
    return events.ConnectorEventBody(**values)


def _automation(**overrides):
    row = {
        "automation_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "u-1",
        "instruction": "Triage it.",
        "trigger_config": {"app": "github", "event": "GITHUB_ISSUE_CREATED"},
        "additional_context": [],
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_a_wrong_secret_is_refused():
    with patch.object(events, "COMPOSIO_WEBHOOK_SECRET", "shh"):
        with pytest.raises(HTTPException) as caught:
            await events.receive_connector_event(_body(), "wrong")
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_an_unknown_composio_user_is_acknowledged_without_a_run():
    with (
        patch.object(events, "COMPOSIO_WEBHOOK_SECRET", "shh"),
        patch.object(
            events.installation_db,
            "get_installation_by_composio_user",
            AsyncMock(return_value=None),
        ),
    ):
        answer = await events.receive_connector_event(_body(), "shh")
    assert answer == {"matched": 0}


@pytest.mark.asyncio
async def test_a_matching_automation_is_dispatched_with_the_event_context():
    scheduler = MagicMock()
    scheduler.server_id = "server-1"
    with (
        patch.object(events, "COMPOSIO_WEBHOOK_SECRET", "shh"),
        patch.object(
            events.installation_db,
            "get_installation_by_composio_user",
            AsyncMock(return_value={"user_id": "u-1"}),
        ),
        patch.object(
            events.auto_db,
            "list_connector_automations",
            AsyncMock(return_value=[_automation()]),
        ),
        patch.object(events.exec_db, "create_execution", AsyncMock(return_value="exec-1")),
        patch.object(events.AutomationScheduler, "get_instance", return_value=scheduler),
    ):
        answer = await events.receive_connector_event(_body(), "shh")

    assert answer == {"matched": 1}
    scheduler.dispatch.assert_called_once()
    automation, execution_id = scheduler.dispatch.call_args.args
    assert execution_id == "exec-1"
    context = automation["additional_context"][0]
    assert context["type"] == "connected_app_event"
    assert context["payload"]["number"] == 7


@pytest.mark.asyncio
async def test_a_filter_that_does_not_match_skips_the_run():
    scheduler = MagicMock()
    scheduler.server_id = "server-1"
    with (
        patch.object(events, "COMPOSIO_WEBHOOK_SECRET", "shh"),
        patch.object(
            events.installation_db,
            "get_installation_by_composio_user",
            AsyncMock(return_value={"user_id": "u-1"}),
        ),
        patch.object(
            events.auto_db,
            "list_connector_automations",
            AsyncMock(
                return_value=[
                    _automation(
                        trigger_config={
                            "app": "github",
                            "event": "GITHUB_ISSUE_CREATED",
                            "filters": {"title": "other"},
                        }
                    )
                ]
            ),
        ),
        patch.object(events.AutomationScheduler, "get_instance", return_value=scheduler),
    ):
        answer = await events.receive_connector_event(_body(), "shh")

    assert answer == {"matched": 0}
    scheduler.dispatch.assert_not_called()
