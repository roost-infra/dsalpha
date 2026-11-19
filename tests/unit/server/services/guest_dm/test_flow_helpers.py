"""Pure helpers of the guest DM flow: token grammar, hashing, invite URLs."""

from __future__ import annotations

from src.server.database.guest_dm import hash_token, new_token
from src.server.services.guest_dm.flow import extract_token, invite_url


def test_extract_token_accepts_a_bare_token() -> None:
    token = "dm_" + "a" * 40
    assert extract_token(token) == token


def test_extract_token_accepts_a_pasted_link() -> None:
    token = "dm_" + "b" * 43
    assert extract_token(f"https://app.example/dm/{token}?x=1") == token


def test_extract_token_rejects_text_without_a_token() -> None:
    assert extract_token("https://app.example/dm/") is None
    assert extract_token("dm_short") is None


def test_hash_token_is_stable_and_not_the_token() -> None:
    token = new_token()
    assert token.startswith("dm_")
    assert len(token) > 30
    digest = hash_token(token)
    assert len(digest) == 64
    assert digest == hash_token(f"  {token}  ")
    assert token not in digest


def test_invite_url_uses_public_app_url(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.example/")
    assert invite_url("dm_x") == "https://app.example/dm/dm_x"
    monkeypatch.delenv("PUBLIC_APP_URL")
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    assert invite_url("dm_x") is None
