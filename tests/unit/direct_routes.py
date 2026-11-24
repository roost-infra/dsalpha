"""The catalog as it was before every model went through the Roost relay.

The relay serves the whole catalog over its OpenAI-compatible endpoint, so
``claude-opus-5-5`` now builds a ``ChatOpenAI`` aimed at the relay. The code
for each provider's own route (Anthropic's Messages API, OpenAI's Responses
API, Gemini, z.ai, DashScope, Moonshot) is still live: hidden entries, BYOK
and custom models reach it. Tests that exercise those routes use the catalog
names as handles, so they run against the entries that sent those names
there, kept in ``fixtures/direct_route_models.json``, without the relay's
twins of those entries.

``test_request_lock`` and the catalog tests read the real manifest and do not
use this.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "direct_route_models.json").read_text())
#: The entries the relay took over, as they were.
DIRECT_ROUTE_MODELS: dict = _FIXTURE["entries"]
#: The visibility and tier the relay changed on the other entries; ``None``
#: means the entry had no such field.
_OVERRIDES: dict = _FIXTURE["overrides"]


def direct_catalog(llm_config: dict) -> dict:
    """``llm_config`` with the relay's entries swapped for the direct routes,
    listed as they were before the relay hid them."""
    # The relay's twin of a direct entry names the same model id, which would
    # leave that id's reasoning lineage ambiguous.
    direct_ids = {info.get("model_id") for info in DIRECT_ROUTE_MODELS.values()}
    catalog = {}
    for key, info in llm_config.items():
        if (
            key not in DIRECT_ROUTE_MODELS
            and isinstance(info, dict)
            and info.get("provider") == "roost"
            and info.get("model_id") in direct_ids
        ):
            continue
        if key in DIRECT_ROUTE_MODELS:
            info = DIRECT_ROUTE_MODELS[key]
        elif key in _OVERRIDES:
            info = {**info, **_OVERRIDES[key]}
            info = {k: v for k, v in info.items() if not (v is None and k in _OVERRIDES[key])}
        catalog[key] = info
    return catalog


def _apply(config) -> None:
    config.llm_config = direct_catalog(config.llm_config)
    config._providers_with_models = frozenset(
        info["provider"]
        for info in config.llm_config.values()
        if info and info.get("visible") and info.get("provider")
    )


def direct_model_config():
    """A ``ModelConfig`` that reads the direct-route catalog."""
    from src.llms.llm import ModelConfig

    config = ModelConfig()
    _apply(config)
    return config


def use_direct_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ``ModelConfig`` built from now on, including the ``LLM``
    singleton, read the direct-route catalog."""
    from src.llms import llm as llm_module

    original = llm_module.ModelConfig.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _apply(self)

    monkeypatch.setattr(llm_module.ModelConfig, "__init__", init)
    monkeypatch.setattr(llm_module.LLM, "_model_config", None)
