"""cl100k_base fetches its BPE file on first use, which the unit suite's
blocked sockets refuse on a cold cache (CI runners). The prefix tests count
what no call measured through it, so the loader is stubbed for the whole
folder."""

from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _offline_token_counter(monkeypatch):
    from ptc_agent.agent.middleware.compaction import utils

    fake = SimpleNamespace(encode=lambda text: [0] * (len(text) // 4 + 1))
    monkeypatch.setattr(utils, "_get_tiktoken_encoder", lambda: fake)


@pytest.fixture(autouse=True)
def _direct_routes(direct_routes):
    """These tests drive each provider's own route by catalog name; see
    ``tests.unit.direct_routes``."""
