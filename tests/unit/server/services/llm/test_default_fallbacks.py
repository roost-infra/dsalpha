"""The deployment's fallback chain, for turns whose user saved none.

A model can go dark at the gateway while the deployment is healthy; without a
chain behind it, every turn naming that model fails even though other models
answer. The user's own list, even an empty one, always wins.
"""

from types import SimpleNamespace

import pytest

from ptc_agent.config.agent import LLMConfig
from src.config import settings
from src.server.services.llm.config import select_model


def _config(fallback=None):
    return SimpleNamespace(llm=LLMConfig(name="main", fallback=fallback), llm_client=None)


def test_a_user_who_saved_no_fallbacks_gets_the_deployments(monkeypatch):
    monkeypatch.setattr(
        settings, "get_default_fallback_models", lambda: ["spare-a", "spare-b"]
    )

    config = _config()

    selection = select_model(config, {}, "primary", None)

    assert selection.users_fallbacks is False
    assert config.llm.fallback == ["spare-a", "spare-b"]


def test_the_users_empty_list_is_kept_over_the_deployments(monkeypatch):
    monkeypatch.setattr(settings, "get_default_fallback_models", lambda: ["spare"])

    config = _config()

    selection = select_model(config, {"fallback_models": []}, "primary", None)

    assert selection.users_fallbacks is True
    assert config.llm.fallback == []


def test_the_users_saved_list_is_kept(monkeypatch):
    monkeypatch.setattr(settings, "get_default_fallback_models", lambda: ["spare"])

    config = _config()

    select_model(config, {"fallback_models": ["mine"]}, "primary", None)

    assert config.llm.fallback == ["mine"]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (None, list(settings.DEFAULT_FALLBACK_MODELS)),
        ("", []),
        (" a , ,b ", ["a", "b"]),
    ],
)
def test_the_env_names_the_chain(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("DEFAULT_FALLBACK_MODELS", raising=False)
    else:
        monkeypatch.setenv("DEFAULT_FALLBACK_MODELS", env)

    assert settings.get_default_fallback_models() == expected
