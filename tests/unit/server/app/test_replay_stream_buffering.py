"""The replay stream reaches the reader as it is built, not when it is finished.

The gateway buffers this route deliberately (it serves the replay as one
compressed body so a slow reader cannot hold a worker). That is fine for a
JSON response and wrong for a stream: everything downstream of the buffer —
including the browser — waits for the last turn of the page before it sees the
first. ``X-Accel-Buffering: no`` is how a response opts itself out of that
buffer without touching the shared gateway config, so this locks the header's
presence: dropping it silently restores the "first page waits for the whole
read" behaviour this change exists to remove.
"""

from unittest.mock import AsyncMock, patch

import pytest
from tests.unit.server.services.history.replay_builders import replay_rows

THREADS_MOD = "src.server.app.threads.messaging"

THREAD = "11111111-1111-1111-1111-111111111111"


def _replay_data():
    """Owner matches create_test_app's override; no checkpoint pointer, so
    replay takes the (empty) stub path without touching a DB."""
    thread = {"conversation_thread_id": THREAD, "latest_checkpoint_id": None}
    return replay_rows(thread, [], [], owner_id="test-user-123")


@pytest.mark.asyncio
async def test_replay_stream_opts_out_of_gateway_buffering(threads_client):
    with patch(
        f"{THREADS_MOD}.get_replay_thread_data",
        new=AsyncMock(return_value=_replay_data()),
    ):
        resp = await threads_client.get(f"/api/v1/threads/{THREAD}/messages/replay")

    assert resp.status_code == 200
    assert resp.headers["x-accel-buffering"] == "no"
    # The stream contract is unchanged: still an event stream, still uncached.
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.asyncio
async def test_an_older_page_also_opts_out(threads_client):
    """Paging back loops for the reader; every page must arrive early too."""
    with patch(
        f"{THREADS_MOD}.get_replay_thread_data",
        new=AsyncMock(return_value=_replay_data()),
    ):
        resp = await threads_client.get(
            f"/api/v1/threads/{THREAD}/messages/replay",
            params={"before_turn": 5, "limit": 20},
        )

    assert resp.status_code == 200
    assert resp.headers["x-accel-buffering"] == "no"
