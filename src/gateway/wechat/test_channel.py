"""Regression tests for WeChat reply extraction, per-user bindings and auth.

The extraction rule was learned the hard way: the first implementation sent the
model's whole thinking process to WeChat, because it kept every ``content``
field that was not ``reasoning_signal``. Reasoning reaches the client under two
other spellings, and the ``tools`` agent reports results as ``text`` too.
"""

from __future__ import annotations

import json

import pytest

from src.gateway.wechat.channel import WeChatChannel, extract_reply
from src.gateway.wechat.state import Binding, BindingStore


def frame(**fields) -> list[str]:
    """One SSE frame: the event-name line, then the data line."""
    event = fields.pop("_event")
    return [f"event: {event}", "data: " + json.dumps(fields, ensure_ascii=False)]


# ── reply extraction ─────────────────────────────────────────────────────


def test_reasoning_is_never_sent() -> None:
    """Both reasoning spellings stay out of the reply."""
    lines = [
        *frame(_event="reasoning_signal", content="start"),
        *frame(_event="reasoning_content", content="Let me think about this."),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content="Let me"),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content=" think."),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning_signal", content="complete"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="答案。"),
    ]
    reply, err = extract_reply(lines)
    assert err is None
    assert reply == "答案。"
    for leaked in ("Let me", "think about this"):
        assert leaked not in reply


def test_tool_results_are_not_sent() -> None:
    """The tools agent reports content_type 'text'; it is not an answer."""
    lines = [
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="先查一下。"),
        *frame(_event="message_chunk", agent="tools", content_type="text",
               content="<raw tool output>", tool_call_id="call_1", status="success"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="结论。"),
    ]
    reply, _ = extract_reply(lines)
    assert "raw tool output" not in reply


def test_reply_is_what_follows_the_last_tool_call() -> None:
    """Pre-tool narration is commentary; the reply comes after the last result."""
    lines = [
        *frame(_event="message_chunk", agent="model:a", content_type="text",
               content="Let me search the vault for that."),
        *frame(_event="tool_calls", tool_calls=[{"name": "search_knowledge_base"}]),
        *frame(_event="tool_call_result", content="ok"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="知识库里"),
        *frame(_event="message_chunk", agent="model:a", content_type="text", content="有 6 条命中。"),
    ]
    reply, _ = extract_reply(lines)
    assert reply == "知识库里有 6 条命中。"
    assert "Let me search" not in reply


def test_error_frame_is_reported_not_sent_as_reply() -> None:
    lines = [*frame(_event="error", error="ANTHROPIC_API_KEY environment variable is not set")]
    reply, err = extract_reply(lines)
    assert reply == ""
    assert err and "ANTHROPIC" in err


def test_no_text_at_all_is_an_empty_reply() -> None:
    """A turn that only reasoned must not produce a partial message."""
    lines = [
        *frame(_event="metadata", run_id="r1"),
        *frame(_event="message_chunk", agent="model:a", content_type="reasoning", content="hmm"),
        *frame(_event="run_end", outcome="success"),
    ]
    reply, err = extract_reply(lines)
    assert reply == ""
    assert err is None


# ── per-user loopback identity ───────────────────────────────────────────
# In HOST_MODE=oss the app resolves every caller to one local user and these
# headers are unnecessary; in platform mode the same calls 401 without them.
# The identity is the binding's own user, so a turn lands in their workspace.

USER = "11111111-2222-3333-4444-555555555555"


def _channel(monkeypatch, user_id: str = USER, **env) -> WeChatChannel:
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return WeChatChannel(Binding(user_id=user_id), BindingStore())


def test_no_service_token_means_no_headers(monkeypatch) -> None:
    assert _channel(monkeypatch)._loopback_headers() == {}


def test_service_token_identifies_the_binding_user(monkeypatch) -> None:
    ch = _channel(monkeypatch, INTERNAL_SERVICE_TOKEN="s3cret")
    assert ch._loopback_headers() == {"X-Service-Token": "s3cret", "X-User-Id": USER}


def test_token_without_an_identity_sends_nothing(monkeypatch) -> None:
    """A service token alone would 401 on X-User-Id; better to send neither."""
    ch = _channel(monkeypatch, user_id="", INTERNAL_SERVICE_TOKEN="s3cret")
    assert ch._loopback_headers() == {}


def test_each_channel_carries_its_own_identity(monkeypatch) -> None:
    """Two users' channels must not share a caller identity."""
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "s3cret")
    a = WeChatChannel(Binding(user_id="user-a"), BindingStore())
    b = WeChatChannel(Binding(user_id="user-b"), BindingStore())
    assert a._loopback_headers()["X-User-Id"] == "user-a"
    assert b._loopback_headers()["X-User-Id"] == "user-b"


# ── binding store ────────────────────────────────────────────────────────


def test_store_round_trips_one_file_per_user(tmp_path) -> None:
    store = BindingStore(tmp_path)
    store.save(Binding(user_id="user-a", account_id="a@im.bot", token="t", workspace_id="w1"))
    store.save(Binding(user_id="user-b", account_id="b@im.bot", token="t2"))

    assert sorted(p.stem for p in tmp_path.glob("*.json")) == ["user-a", "user-b"]
    a = store.load("user-a")
    assert a is not None and a.account_id == "a@im.bot" and a.workspace_id == "w1"
    assert set(store.all()) == {"user-a", "user-b"}
    assert store.load("user-a").mode == "ptc"
    assert store.load("user-b").mode == "flash"

    store.delete("user-a")
    assert store.load("user-a") is None
    assert set(store.all()) == {"user-b"}


def test_store_refuses_a_path_shaped_user_id(tmp_path) -> None:
    """A user id reaches the filesystem; it must not be able to escape."""
    store = BindingStore(tmp_path)
    for bad in ("../../etc/passwd", "a/b", ".hidden", ""):
        assert store.load(bad) is None
        with pytest.raises(ValueError):
            store.save(Binding(user_id=bad, account_id="x", token="y"))


def test_store_survives_a_corrupt_file(tmp_path) -> None:
    """One bad file costs that user a re-scan, not the whole manager."""
    store = BindingStore(tmp_path)
    store.save(Binding(user_id="good", account_id="g@im.bot", token="t"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert set(store.all()) == {"good"}
