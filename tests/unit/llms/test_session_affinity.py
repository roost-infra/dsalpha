import uuid

from src.llms.llm import (
    _anthropic_metadata,
    _derive_codex_affinity,
    _session_affinity_headers,
)


def test_affinity_is_a_deterministic_uuid():
    first = _derive_codex_affinity("session-abc")
    second = _derive_codex_affinity("session-abc")
    assert first == second
    assert uuid.UUID(first)


def test_session_header_carries_the_affinity():
    assert _session_affinity_headers("session-abc") == {
        "session-id": _derive_codex_affinity("session-abc")
    }
    assert _session_affinity_headers("") == {}


def test_anthropic_metadata_uses_the_session_suffix_the_relay_parses():
    metadata = _anthropic_metadata("session-abc")
    assert metadata["user_id"].startswith("roost_session_")
    assert metadata["user_id"].removeprefix("roost_session_") == _derive_codex_affinity(
        "session-abc"
    )
    assert _anthropic_metadata("") == {}
