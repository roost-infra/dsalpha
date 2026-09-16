"""Unit tests for the iLink port.

Everything is driven through `httpx.MockTransport` — no test touches the
network. The pure wire logic (chunking, caching, error-code classification) is
tested directly; the loop/HTTP paths are tested against recorded payload shapes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import pytest
from structlog.testing import capture_logs

from src.gateway.ilink import (
    BASE_URL,
    MAX_MESSAGE_LENGTH,
    PollConfig,
    QRResult,
    assert_weixin_host,
    err_code_of,
    extract_text,
    fetch_qr,
    is_session_expired,
    is_stale_session_code,
    poll_qr,
    split_text_chunks,
    start_poll,
)
from src.gateway.ilink import client as ilink_client
from src.gateway.ilink import qr as ilink_qr
from src.gateway.ilink.client import ILinkClient
from src.gateway.ilink.models import (
    Creds,
    ILinkAPIError,
    ILinkError,
    ILinkHTTPError,
    ILinkTimeoutError,
    InboundMessage,
)
from src.gateway.ilink.poll import Deduper, normalize_creds

BASE = "https://ilink.test"
ACCOUNT = "bot-1"
TOKEN = "tok-1"


@contextlib.asynccontextmanager
async def make_client(handler, **kwargs):
    client = ILinkClient(
        ACCOUNT, TOKEN, BASE, transport=httpx.MockTransport(handler), **kwargs
    )
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def no_send_delays(monkeypatch):
    """The production send pacing is 1.5s between chunks and 1-3s per retry."""
    monkeypatch.setattr(ilink_client, "SEND_CHUNK_DELAY_SEC", 0.0)
    monkeypatch.setattr(ilink_client, "SEND_RETRY_DELAY_SEC", 0.0)


async def stop(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# ── pure wire logic ──


@pytest.mark.parametrize(
    ("text", "max_len", "want_parts"),
    [
        ("你好", 10, 1),
        ("a" * 25, 10, 3),
        ("line1\nline2\nline3", 12, 2),
    ],
)
def test_split_text_chunks(text, max_len, want_parts):
    parts = split_text_chunks(text, max_len)
    assert len(parts) == want_parts
    assert "".join(parts) == text
    assert all(len(part.encode("utf-8")) <= max_len for part in parts)


def test_split_text_chunks_never_cuts_a_rune():
    text = "你" * 701  # 3 bytes each → 2103 bytes
    parts = split_text_chunks(text, 2000)
    assert len(parts) == 2
    assert "".join(parts) == text
    # decode() above already proves byte validity; this pins the boundary.
    assert all(part.encode("utf-8").decode("utf-8") == part for part in parts)


def test_extract_text_prefers_text_over_voice():
    assert extract_text({"item_list": [{"type": 1, "text_item": {"text": "你好"}}]}) == "你好"
    assert (
        extract_text({"item_list": [{"type": 3, "voice_item": {"text": "语音"}}]}) == "语音"
    )
    assert (
        extract_text(
            {
                "item_list": [
                    {"type": 3, "voice_item": {"text": "voice"}},
                    {"type": 1, "text_item": {"text": "text"}},
                ]
            }
        )
        == "text"
    )
    assert extract_text({}) == ""


@pytest.mark.parametrize(
    ("body", "want"),
    [
        ({"errcode": 0, "ret": 0}, 0),
        ({"errcode": -14}, -14),
        ({"ret": 3}, 3),
        ({"errcode": 0, "ret": 5}, 5),
        ({}, 0),
        ({"errcode": None, "ret": None}, 0),
    ],
)
def test_err_code_of(body, want):
    assert err_code_of(body) == want


@pytest.mark.parametrize(
    ("code", "errmsg", "want"),
    [
        (-14, "whatever", True),
        (-2, "unknown error", True),
        (-2, "Unknown Error ", True),
        (-2, "frequency limit", False),
        (-2, "", False),
        (5, "unknown error", False),
    ],
)
def test_is_stale_session_code(code, errmsg, want):
    assert is_stale_session_code(code, errmsg) is want


def test_is_session_expired_from_code_and_from_text():
    api_error = ILinkAPIError(
        "ilink getupdates ret=0 errcode=-14 errmsg=session timeout",
        code=-14,
        errmsg="session timeout",
    )
    assert is_session_expired(api_error)
    stale = ILinkAPIError("boom", code=-2, errmsg="Unknown Error")
    assert is_session_expired(stale)
    rate_limited = ILinkAPIError("boom", code=-2, errmsg="frequency limit")
    assert not is_session_expired(rate_limited)
    # A foreign exception still classifies on the Go implementation's text.
    assert is_session_expired(RuntimeError("ilink getupdates errcode=-14 errmsg=x"))
    assert not is_session_expired(RuntimeError("ilink getupdates errcode=5"))


@pytest.mark.parametrize(
    ("value", "want"),
    [
        (None, None),
        (Creds("a", "t"), Creds("a", "t")),
        (("a", "t", BASE, True), Creds("a", "t", BASE)),
        (("a", "t", BASE, False), None),
        (("a", "t", BASE), Creds("a", "t", BASE)),
        (("", "t", BASE, True), None),
        (Creds("", ""), None),
    ],
)
def test_normalize_creds(value, want):
    assert normalize_creds(value) == want


def test_normalize_creds_rejects_unknown_shape():
    with pytest.raises(TypeError):
        normalize_creds("acct|tok")  # type: ignore[arg-type]


def test_deduper_bounds_and_resets():
    deduper = Deduper()
    assert not deduper.is_seen("m1")
    deduper.add("m1")
    assert deduper.is_seen("m1")
    assert not deduper.is_seen("")  # empty id never dedups
    deduper.add("")
    assert len(deduper) == 1

    for i in range(Deduper.SEEN_CAP + 1):
        deduper.add(f"bulk-{i}")
    expired = "old"
    deduper._seen[expired] = 0.0  # an entry older than the TTL
    deduper.add("trigger")  # crosses the cap → sweep runs
    assert not deduper.is_seen(expired)
    assert deduper.is_seen("trigger")

    deduper.reset()
    assert len(deduper) == 0


# ── credentials and the context_token cache ──


@pytest.mark.asyncio
async def test_context_token_cache_is_soft_capped():
    async with make_client(lambda request: httpx.Response(200, json={}), ctx_tokens_cap=4) as c:
        for i in range(4):
            c.set_context_token(f"peer-{i}", f"tok-{i}")
        assert c.context_token_for("peer-0") == "tok-0"

        c.set_context_token("peer-4", "tok-4")  # cap reached → whole map dropped
        assert c.context_token_for("peer-0") == ""
        assert c.context_token_for("peer-4") == "tok-4"

        c.set_context_token("", "tok")  # empty peer/token are ignored
        c.set_context_token("peer-5", "")
        assert c.context_token_for("peer-5") == ""


@pytest.mark.asyncio
async def test_set_creds_trims_base_url_and_drops_account_scoped_caches():
    async with make_client(lambda request: httpx.Response(200, json={})) as c:
        c.set_context_token("peer", "tok")
        c.set_creds("bot-2", "tok-2", BASE + "/")
        assert c.creds == Creds("bot-2", "tok-2", BASE)
        assert c.context_token_for("peer") == ""

        # Same account → the caches survive (a token rotation is not a new session).
        c.set_context_token("peer", "tok")
        c.set_creds("bot-2", "tok-3", BASE)
        assert c.creds == Creds("bot-2", "tok-3", BASE)
        assert c.context_token_for("peer") == "tok"

        # An empty base_url falls back to the production host (Go parity).
        c.set_creds("bot-2", "tok-4")
        assert c.creds.base_url == BASE_URL


# ── sendmessage ──


@pytest.mark.asyncio
async def test_send_text_rejects_blank_text():
    async with make_client(lambda request: httpx.Response(200, json={})) as c:
        with pytest.raises(ValueError):
            await c.send_text("peer", "   ")


@pytest.mark.asyncio
async def test_send_text_envelope_echoes_context_token_and_mints_client_ids():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ret": 0, "errcode": 0})

    async with make_client(handler) as c:
        c.set_context_token("peer-1", "ctx-token-1")
        await c.send_text("peer-1", "你好，Athena")
        await c.send_text("peer-1", "第二条")

    assert len(seen) == 2
    first = seen[0]["msg"]
    assert first["context_token"] == "ctx-token-1"
    assert first["to_user_id"] == "peer-1"
    assert first["from_user_id"] == ""
    assert first["message_type"] == 2
    assert first["message_state"] == 2
    assert first["item_list"] == [{"type": 1, "text_item": {"text": "你好，Athena"}}]
    assert seen[0]["base_info"]["channel_version"] == "2.2.0"
    # Message fields must live inside the envelope, not at the top level.
    assert "to_user_id" not in seen[0]
    ids = [body["msg"]["client_id"] for body in seen]
    assert ids[0].startswith("athena-weixin-")
    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_send_text_chunks_long_text(no_send_delays):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ret": 0})

    long_text = "段" * 1600  # 4800 bytes → 3 chunks
    async with make_client(handler) as c:
        await c.send_text("peer-1", long_text)

    assert len(seen) == 3
    chunks = [body["msg"]["item_list"][0]["text_item"]["text"] for body in seen]
    assert "".join(chunks) == long_text
    assert all(len(chunk.encode("utf-8")) <= MAX_MESSAGE_LENGTH for chunk in chunks)


@pytest.mark.asyncio
async def test_send_text_session_expired_retries_tokenless(no_send_delays):
    seen: list[dict] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        seen.append(json.loads(request.content))
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"errcode": -14, "errmsg": "session expired"})
        return httpx.Response(200, json={"ret": 0})

    async with make_client(handler) as c:
        c.set_context_token("peer-1", "stale-token")
        await c.send_text("peer-1", "push after expiry")  # must not raise
        assert c.context_token_for("peer-1") == ""

    assert len(seen) == 2
    assert seen[0]["msg"]["context_token"] == "stale-token"
    assert "context_token" not in seen[1]["msg"]


@pytest.mark.asyncio
async def test_send_text_client_id_pinned_across_retries(no_send_delays):
    seen: list[dict] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        seen.append(json.loads(request.content))
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"errcode": 5, "errmsg": "transient"})
        return httpx.Response(200, json={"ret": 0})

    async with make_client(handler) as c:
        await c.send_text("peer-1", "retry me")

    assert len(seen) == 2
    assert seen[0]["msg"]["client_id"] == seen[1]["msg"]["client_id"]


@pytest.mark.asyncio
async def test_send_text_bare_rate_limit_keeps_the_context_token(no_send_delays):
    seen: list[dict] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        seen.append(json.loads(request.content))
        calls += 1
        if calls <= 2:
            return httpx.Response(200, json={"errcode": -2})
        return httpx.Response(200, json={"ret": 0})

    async with make_client(handler) as c:
        c.set_context_token("peer-1", "keep-me")
        await c.send_text("peer-1", "limited")
        assert c.context_token_for("peer-1") == "keep-me"

    assert len(seen) == 3
    assert all(body["msg"]["context_token"] == "keep-me" for body in seen)


@pytest.mark.asyncio
async def test_send_text_gives_up_after_retries_with_the_api_error(no_send_delays):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"errcode": 5, "errmsg": "nope"})

    async with make_client(handler) as c:
        with pytest.raises(ILinkAPIError) as excinfo:
            await c.send_text("peer-1", "dead")
        assert excinfo.value.code == 5

    assert calls == 5  # 1 + sendRetries


@pytest.mark.asyncio
async def test_send_text_reports_http_errors(no_send_delays):
    async with make_client(lambda request: httpx.Response(500, text="upstream boom")) as c:
        with pytest.raises(ILinkHTTPError) as excinfo:
            await c.send_text("peer-1", "hi")
    assert "HTTP 500" in str(excinfo.value)
    assert "upstream boom" in str(excinfo.value)


@pytest.mark.asyncio
async def test_request_headers_carry_auth_and_app_identity():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ret": 0})

    async with make_client(handler) as c:
        await c.send_text("peer-1", "hi")
        await c.get_config()

    post, get = requests
    assert post.headers["Authorization"] == f"Bearer {TOKEN}"
    assert post.headers["AuthorizationType"] == "ilink_bot_token"
    assert post.headers["iLink-App-Id"] == "bot"
    assert post.headers["iLink-App-ClientVersion"] == "131584"
    assert post.headers["Content-Type"] == "application/json"
    assert post.headers["X-WECHAT-UIN"]
    assert post.url.path == "/ilink/bot/sendmessage"

    assert get.method == "GET"
    assert get.headers["Authorization"] == f"Bearer {TOKEN}"
    assert get.url.path == "/ilink/bot/getconfig"


@pytest.mark.asyncio
async def test_credentials_never_reach_the_logs(no_send_delays):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": -14, "errmsg": "session expired"})

    secret = "SUPER-SECRET-BOT-TOKEN"
    with capture_logs() as logs:
        client = ILinkClient(
            ACCOUNT, secret, BASE, transport=httpx.MockTransport(handler), ctx_tokens_cap=2
        )
        async with client:
            client.set_context_token("peer-1", "stale-token")
            with pytest.raises(ILinkAPIError):
                await client.send_text("peer-1", "push")
        assert logs  # the failure path did log

    for entry in logs:
        assert secret not in json.dumps(entry)
        assert "stale-token" not in json.dumps(entry)


# ── getupdates ──


@pytest.mark.asyncio
async def test_get_updates_parses_messages_and_caches_context_tokens():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ret": 0,
                "errcode": 0,
                "get_updates_buf": "cursor-1",
                "longpolling_timeout_ms": 30000,
                "msgs": [
                    {
                        "from_user_id": ACCOUNT,  # the bot's own echo
                        "message_id": "self-1",
                        "msg_type": 1,
                        "item_list": [{"type": 1, "text_item": {"text": "my reply"}}],
                    },
                    {
                        "from_user_id": "user-9",
                        "message_id": "m-1",
                        "msg_type": 1,
                        "context_token": "tok-user-9",
                        "item_list": [{"type": 1, "text_item": {"text": "在吗"}}],
                    },
                    {"from_user_id": "", "message_id": "m-2"},
                ],
            },
        )

    async with make_client(handler) as c:
        result = await c.get_updates("", 500)
        assert result.sync_buf == "cursor-1"
        assert result.suggested_timeout_ms == 30000
        assert result.messages == [
            InboundMessage("user-9", "m-1", 1, "在吗", "tok-user-9")
        ]
        assert c.context_token_for("user-9") == "tok-user-9"


@pytest.mark.asyncio
async def test_get_updates_keeps_the_cursor_when_the_server_omits_one():
    async with make_client(lambda request: httpx.Response(200, json={"ret": 0})) as c:
        result = await c.get_updates("cursor-kept", 500)
    assert result.sync_buf == "cursor-kept"
    assert result.messages == []
    assert result.suggested_timeout_ms == 0


@pytest.mark.asyncio
async def test_get_updates_treats_a_timeout_as_an_empty_poll():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("poll window elapsed", request=request)

    async with make_client(handler) as c:
        result = await c.get_updates("cursor-1", 500)
    assert result.sync_buf == "cursor-1"
    assert result.messages == []


@pytest.mark.asyncio
async def test_get_updates_raises_a_typed_session_expiry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ret": -14, "errcode": -14, "errmsg": "timeout"})

    async with make_client(handler) as c:
        with pytest.raises(ILinkAPIError) as excinfo:
            await c.get_updates("", 500)
    assert excinfo.value.code == -14
    # The Go-style message is preserved for callers that match on text.
    assert "errcode=-14" in str(excinfo.value)
    assert "ilink getupdates" in str(excinfo.value)


# ── typing indicator ──


@pytest.mark.asyncio
async def test_typing_ticket_is_fetched_once_and_cached():
    paths: list[str] = []
    typing_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("getconfig"):
            return httpx.Response(200, json={"typing_ticket": "ticket-123"})
        typing_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"ret": 0})

    async with make_client(handler) as c:
        await c.send_typing("user-9", True)
        await c.send_typing("user-9", True)
        await c.send_typing("user-9", False)

    assert sum(path.endswith("getconfig") for path in paths) == 1
    assert len(typing_bodies) == 3
    assert typing_bodies[0] == {
        "ilink_user_id": "user-9",
        "typing_ticket": "ticket-123",
        "status": 1,
    }
    assert typing_bodies[2]["status"] == 2


@pytest.mark.asyncio
async def test_typing_without_a_ticket_does_not_send():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={})

    async with make_client(handler) as c:
        with pytest.raises(ILinkError, match="no typing_ticket"):
            await c.send_typing("user-9", True)
    assert all(path.endswith("getconfig") for path in paths)


@pytest.mark.asyncio
async def test_send_typing_rejects_an_empty_peer():
    async with make_client(lambda request: httpx.Response(200, json={})) as c:
        with pytest.raises(ValueError):
            await c.send_typing("", True)


# ── poll loop ──


@pytest.mark.asyncio
async def test_poll_loop_idles_without_credentials():
    hits = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        await asyncio.sleep(0.02)  # pace the hot loop
        return httpx.Response(200, json={"ret": 0, "errcode": 0, "msgs": []})

    bound = False

    def provider():
        if bound:
            return Creds(ACCOUNT, TOKEN, BASE)
        return None

    cfg = PollConfig(long_poll_timeout_ms=500, keepalive_sec=3600, cred_check_sec=0.05)
    client = ILinkClient(ACCOUNT, TOKEN, BASE, transport=httpx.MockTransport(handler))
    task = start_poll(client, provider, lambda from_, text: "", cfg=cfg)
    try:
        await asyncio.sleep(0.3)
        assert hits == 0  # unbound: the loop must stay off the network

        bound = True
        for _ in range(100):
            if hits:
                break
            await asyncio.sleep(0.02)
        assert hits > 0, "loop did not revive after credentials appeared"

        bound = False
        await asyncio.sleep(0.4)  # > cred_check_sec; the loop parks again
        settled = hits
        await asyncio.sleep(0.3)
        assert hits == settled, f"loop kept polling after unbind: {settled} → {hits}"
    finally:
        await stop(task)
        await client.aclose()


@pytest.mark.asyncio
async def test_poll_loop_replies_inline_and_echoes_the_inbound_context_token():
    sent: list[tuple[str, str]] = []
    send_bodies: list[dict] = []
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url.path.endswith("sendmessage"):
            send_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"ret": 0})
        if not request.url.path.endswith("getupdates"):
            return httpx.Response(200, json={"ret": 0})  # getconfig keepalive
        polls += 1
        if polls == 1:
            return httpx.Response(
                200,
                json={
                    "ret": 0,
                    "get_updates_buf": "cursor-1",
                    "msgs": [
                        {
                            "from_user_id": "user-9",
                            "message_id": "m-1",
                            "msg_type": 1,
                            "context_token": "tok-user-9",
                            "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"ret": 0, "msgs": []})

    async def handler_func(from_: str, text: str) -> str:
        return f"pong:{text}"

    cfg = PollConfig(long_poll_timeout_ms=100, keepalive_sec=3600, cred_check_sec=0.05)
    client = ILinkClient("", "", BASE, transport=httpx.MockTransport(handler))

    async def send_func(to: str, text: str) -> None:
        sent.append((to, text))
        await client.send_text(to, text)  # the real wiring's sendFunc

    task = start_poll(client, lambda: Creds(ACCOUNT, TOKEN, BASE), handler_func, send_func, cfg)
    try:
        for _ in range(100):
            if sent:
                break
            await asyncio.sleep(0.02)
        assert sent == [("user-9", "pong:hi")]
    finally:
        await stop(task)
        await client.aclose()

    assert send_bodies[0]["msg"]["context_token"] == "tok-user-9"
    assert send_bodies[0]["msg"]["to_user_id"] == "user-9"


@pytest.mark.asyncio
async def test_poll_loop_dedups_replayed_messages():
    handled: list[str] = []
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if not request.url.path.endswith("getupdates"):
            return httpx.Response(200, json={"ret": 0})  # getconfig keepalive
        polls += 1
        # Every poll replays the same message, as a lost-response retry does.
        return httpx.Response(
            200,
            json={
                "ret": 0,
                "msgs": [
                    {
                        "from_user_id": "user-9",
                        "message_id": "m-dup",
                        "msg_type": 1,
                        "item_list": [{"type": 1, "text_item": {"text": "once"}}],
                    }
                ],
            },
        )

    def handler_func(from_: str, text: str) -> str:
        handled.append(text)
        return ""

    cfg = PollConfig(long_poll_timeout_ms=20, keepalive_sec=3600, cred_check_sec=0.05)
    client = ILinkClient(ACCOUNT, TOKEN, BASE, transport=httpx.MockTransport(handler))
    task = start_poll(client, lambda: Creds(ACCOUNT, TOKEN, BASE), handler_func, None, cfg)
    try:
        for _ in range(100):
            if len(handled) >= 1:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)  # several more polls replay the same id
        assert handled == ["once"]
    finally:
        await stop(task)
        await client.aclose()


@pytest.mark.asyncio
async def test_poll_loop_handler_error_replies_with_the_apology_and_drops_empty_replies():
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sendmessage"):
            sent.append(json.loads(request.content)["msg"]["item_list"][0]["text_item"]["text"])
            return httpx.Response(200, json={"ret": 0})
        if not request.url.path.endswith("getupdates"):
            return httpx.Response(200, json={"ret": 0})  # getconfig keepalive
        return httpx.Response(
            200,
            json={
                "ret": 0,
                "msgs": [
                    {
                        "from_user_id": "user-9",
                        "message_id": "m-1",
                        "msg_type": 1,
                        "item_list": [{"type": 1, "text_item": {"text": "boom"}}],
                    },
                    {
                        "from_user_id": "user-10",
                        "message_id": "m-2",
                        "msg_type": 1,
                        "item_list": [{"type": 1, "text_item": {"text": "silent"}}],
                    },
                ],
            },
        )

    async def send_func(to: str, text: str) -> None:
        sent.append(text)

    def handler_func(from_: str, text: str) -> str:
        if text == "boom":
            raise RuntimeError("handler blew up")
        return ""

    cfg = PollConfig(long_poll_timeout_ms=20, keepalive_sec=3600, cred_check_sec=0.05)
    client = ILinkClient(ACCOUNT, TOKEN, BASE, transport=httpx.MockTransport(handler))
    task = start_poll(client, lambda: Creds(ACCOUNT, TOKEN, BASE), handler_func, send_func, cfg)
    try:
        for _ in range(100):
            if sent:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)
        assert sent == ["抱歉，处理消息时出错了，请稍后再试。"]
    finally:
        await stop(task)
        await client.aclose()


@pytest.mark.asyncio
async def test_poll_loop_resets_the_cursor_when_credentials_change():
    """A rebind is a new session: the in-memory cursor must not be reused."""
    seen_bufs: list[str] = []
    creds_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("getupdates"):
            return httpx.Response(200, json={"ret": 0})  # getconfig keepalive
        seen_bufs.append(json.loads(request.content)["get_updates_buf"])
        return httpx.Response(200, json={"ret": 0, "get_updates_buf": "cursor-A"})

    def provider():
        nonlocal creds_calls
        creds_calls += 1
        if creds_calls > 2:
            return Creds("bot-2", "tok-2", BASE)  # fresh QR bind
        return Creds(ACCOUNT, TOKEN, BASE)

    cfg = PollConfig(long_poll_timeout_ms=20, keepalive_sec=3600, cred_check_sec=0.05)
    client = ILinkClient("", "", BASE, transport=httpx.MockTransport(handler))
    task = start_poll(client, provider, lambda from_, text: "", None, cfg)
    try:
        for _ in range(100):
            if client.creds.account_id == "bot-2":
                break
            await asyncio.sleep(0.02)
        for _ in range(100):
            if len(seen_bufs) >= 3:
                break
            await asyncio.sleep(0.02)
    finally:
        await stop(task)
        await client.aclose()

    assert "cursor-A" in seen_bufs
    first_cursor = seen_bufs.index("cursor-A")
    assert "" in seen_bufs[first_cursor + 1 :]  # cursor dropped on the credential change


# ── QR bind flow ──


@pytest.mark.parametrize(
    "url",
    [
        BASE_URL,
        "https://ilinkai.weixin.qq.com",
        "https://ilink-sh.weixin.qq.com",
        "https://any-host.weixin.qq.com",
    ],
)
def test_weixin_host_allowlist_accepts_tencent_hosts(url):
    assert_weixin_host(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://ilinkai.weixin.qq.com",  # not https
        "https://evil.example.com",  # foreign host
        "https://weixin.qq.com.evil.example.com",  # suffix trick
        "https://evil.weixin.qq.com.attacker.io",  # suffix trick
        "http://127.0.0.1:9938",  # internal address
        "https://postgres:5432",  # internal service
        "",
    ],
)
def test_weixin_host_allowlist_rejects_everything_else(url):
    with pytest.raises(ILinkHTTPError):
        assert_weixin_host(url)


@pytest.mark.asyncio
async def test_poll_qr_rejects_a_foreign_base_before_any_request():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ILinkHTTPError, match="not an allowed WeChat host"):
            await poll_qr("qr-token", "https://postgres:5432", client=http)
    assert not called


@pytest.mark.asyncio
async def test_fetch_qr_returns_the_value_and_image():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["bot_type"] == "3"
        assert request.headers["iLink-App-Id"] == "bot"
        return httpx.Response(
            200, json={"qrcode": "qr-token", "qrcode_img_content": "https://weixin/liteapp"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        qr_value, image = await fetch_qr(client=http)
    assert (qr_value, image) == ("qr-token", "https://weixin/liteapp")


@pytest.mark.asyncio
async def test_fetch_qr_errors_on_an_empty_qrcode():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as http:
        with pytest.raises(ILinkHTTPError, match="empty qrcode"):
            await fetch_qr(client=http)


@pytest.mark.asyncio
async def test_poll_qr_parses_confirmed_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["qrcode"] == "qr-token"
        return httpx.Response(
            200,
            json={
                "status": "confirmed",
                "ilink_bot_id": "bot-123",
                "bot_token": "tok-abc",
                "baseurl": "https://ilink-sh.weixin.qq.com",
                "ilink_user_id": "user-777",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await poll_qr("qr-token", client=http, guard=lambda url: None)
    assert result == QRResult(
        status="confirmed",
        account_id="bot-123",
        token="tok-abc",
        base_url="https://ilink-sh.weixin.qq.com",
        user_id="user-777",
    )
    assert result.confirmed
    assert result.creds == Creds("bot-123", "tok-abc", "https://ilink-sh.weixin.qq.com")


@pytest.mark.asyncio
async def test_poll_qr_reports_redirect_host_and_defaults():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "scaned_but_redirect", "redirect_host": " ilink-gz.weixin.qq.com "}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await poll_qr("qr-token", client=http, guard=lambda url: None)
    assert result.status == "scaned_but_redirect"
    assert result.redirect_base == "https://ilink-gz.weixin.qq.com"
    assert result.base_url == BASE_URL  # empty baseurl → default host


@pytest.mark.asyncio
async def test_poll_qr_reports_a_timeout_as_the_timeout_subclass():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("held open", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ILinkTimeoutError) as excinfo:
            await poll_qr("qr-token", client=http, guard=lambda url: None)
    assert isinstance(excinfo.value, ILinkHTTPError)  # still catchable broadly


@pytest.mark.asyncio
async def test_poll_qr_defaults_a_missing_status_to_wait():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as http:
        result = await poll_qr("qr-token", client=http, guard=lambda url: None)
    assert result == QRResult()
    assert not result.confirmed
    assert result.creds is None


def test_redirect_base_of():
    assert ilink_qr.redirect_base_of("") == ""
    assert ilink_qr.redirect_base_of("  h.example  ") == "https://h.example"


# ── protocol constants are the ones the gateway expects ──


def test_wire_constants_are_pinned():
    from src.gateway.ilink import models

    assert models.BASE_URL == "https://ilinkai.weixin.qq.com"
    assert models.APP_ID == "bot"
    assert models.APP_CLIENT_VERSION == "131584"
    assert models.CHANNEL_VERSION == "2.2.0"
    assert models.EP_GET_UPDATES == "ilink/bot/getupdates"
    assert models.EP_SEND_MESSAGE == "ilink/bot/sendmessage"
    assert models.EP_GET_CONFIG == "ilink/bot/getconfig"
    assert models.EP_SEND_TYPING == "ilink/bot/sendtyping"
    assert models.EP_GET_BOT_QR == "ilink/bot/get_bot_qrcode"
    assert models.EP_GET_QR_STATUS == "ilink/bot/get_qrcode_status"
    assert models.LONG_POLL_TIMEOUT_MS == 35_000
    assert models.MAX_MESSAGE_LENGTH == 2000
    assert models.SEND_RETRIES == 4
    assert models.SESSION_EXPIRED_ERR_CODE == -14
    assert models.RATE_LIMIT_ERR_CODE == -2
    assert models.CTX_TOKENS_CAP == 4096
