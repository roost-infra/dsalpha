"""Endpoint transport streams an assembled page, not incremental projection.

Use ASGI send messages: httpx.ASGITransport buffers the whole response and
cannot establish first-event timing or cancellation while the tail is pending.
"""

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import create_test_app
from tests.unit.server.services.history.replay_builders import replay_rows

THREADS_MOD = "src.server.app.threads.messaging"
REPLAY_MOD = "src.server.services.history.replay"
THREAD = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True])
async def test_replay_endpoint_transport_timing_order_and_disconnect(disconnect):
    from src.server.app.setup import _SelectiveGZip
    from src.server.app.threads import router
    from src.server.services.history.replay import ReplayPage
    from src.server.services.history.replay.lines import line_of

    app = _SelectiveGZip(create_test_app(router), minimum_size=1)
    rows = replay_rows(
        {"conversation_thread_id": THREAD, "latest_checkpoint_id": "tip",
         "latest_run_id": "latest"}, [], [], owner_id="test-user-123",
    )
    projection_entered = asyncio.Event()
    projection_release = asyncio.Event()
    finish_entered = asyncio.Event()
    finish_release = asyncio.Event()
    snapshot_entered = asyncio.Event()
    snapshot_release = asyncio.Event()
    snapshot_closed = asyncio.Event()
    disconnected = asyncio.Event()
    messages = []
    trace = []

    async def project(*args, **kwargs):
        assert kwargs == {"source": "auto", "before_turn": None, "limit": 2}
        projection_entered.set()
        # A ready first turn still cannot leave while the second is projected.
        lines = [line_of({"event": "user_message", "data": {"turn_index": 1}})]
        await projection_release.wait()
        lines.append(line_of({"event": "user_message", "data": {"turn_index": 2}}))
        trace.append("projection_done")
        return ReplayPage(lines, 1, True), "checkpoint"

    async def finish(*args):
        finish_entered.set()
        await finish_release.wait()
        trace.append("finish_done")

    async def snapshot(*args):
        snapshot_entered.set()
        try:
            await snapshot_release.wait()
            return {"runs": []}
        finally:
            snapshot_closed.set()

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            trace.append("body")

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": f"/api/v1/threads/{THREAD}/messages/replay", "root_path": "",
        "query_string": b"limit=2", "headers": [(b"accept-encoding", b"gzip")],
        "client": ("127.0.0.1", 1234), "server": ("test", 80),
    }
    with ExitStack() as stack:
        stack.enter_context(patch(f"{THREADS_MOD}.get_replay_thread_data", AsyncMock(return_value=rows)))
        stack.enter_context(patch(f"{REPLAY_MOD}.read_replay_page", project))
        stack.enter_context(patch(f"{REPLAY_MOD}.finish_lines", finish))
        stack.enter_context(patch("src.server.services.history.snapshot.build_thread_snapshot", snapshot))
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(projection_entered.wait(), 5)
            assert messages == []  # Explicitly document the projection limitation.
            projection_release.set()
            await asyncio.wait_for(finish_entered.wait(), 5)
            assert messages == []  # Widget/task finalization also precedes headers.
            finish_release.set()
            await asyncio.wait_for(snapshot_entered.wait(), 5)
            headers = dict(messages[0]["headers"])
            assert headers[b"x-accel-buffering"] == b"no"
            assert b"content-encoding" not in headers
            assert headers[b"x-replay-source"] == b"checkpoint"
            assert trace[:2] == ["projection_done", "finish_done"]
            # Actual endpoint body is already sent while its tail is blocked.
            body = b"".join(m.get("body", b"") for m in messages).decode()
            frames = [frame.splitlines() for frame in body.strip().split("\n\n")]
            assert [f[0] for f in frames] == ["id: 1", "id: 2", "id: 3"]
            assert [f[1] for f in frames] == ["event: history_page", "event: user_message", "event: user_message"]
            assert json.loads(frames[0][2][6:]) == {"first_turn_index": 1, "has_more": True}
            assert [json.loads(f[2][6:])["turn_index"] for f in frames[1:]] == [1, 2]
            if disconnect:
                disconnected.set()
            else:
                snapshot_release.set()
            await asyncio.wait_for(task, 5)
            assert snapshot_closed.is_set()  # No detached snapshot read on disconnect.
            body = b"".join(m.get("body", b"") for m in messages).decode()
            if disconnect:
                assert "event: replay_done" not in body
                assert "event: snapshot" not in body
            else:
                assert body.index("id: 4\nevent: snapshot") < body.index("id: 5\nevent: replay_done")
                assert json.loads(body.strip().split("\n\n")[-1].splitlines()[2][6:]) == {
                    "thread_id": THREAD, "latest_run_id": "latest",
                }
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
