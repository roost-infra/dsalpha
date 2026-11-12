"""The Content Desk operation vocabulary: bounded, optimistic, user-owned."""

import pytest

from src.server.app.content_desk import _default_state, apply_ops


def test_add_update_and_delete_item():
    state = _default_state()
    state = apply_ops(state, [{"op": "add_item", "title": "第一版", "body": "正文"}])
    assert len(state["items"]) == 1
    item_id = state["items"][0]["id"]

    state = apply_ops(state, [{"op": "update_item", "id": item_id, "title": "改过", "status": "draft"}])
    assert state["items"][0]["title"] == "改过"
    assert state["items"][0]["status"] == "draft"

    state = apply_ops(state, [{"op": "delete_item", "id": item_id}])
    assert state["items"] == []


def test_bad_fields_are_dropped_not_raised():
    state = _default_state()
    state = apply_ops(state, [{"op": "add_item", "title": "x", "kind": "evil", "tags": "nope"}])
    assert state["items"][0]["kind"] == "note"
    assert state["items"][0]["tags"] == []


def test_styles_and_metrics_are_bounded():
    state = _default_state()
    state = apply_ops(state, [{"op": "add_style", "name": "口播", "rules": "短句"}])
    assert state["styles"][0]["name"] == "口播"
    state = apply_ops(state, [{"op": "add_metric", "date": "2026-11-12", "views": 10, "likes": 2}])
    assert state["metrics"][0]["views"] == 10


def test_unknown_op_does_not_mutate():
    state = _default_state()
    assert apply_ops(state, [{"op": "drop_database"}]) == state


def test_requires_an_id_for_updates():
    with pytest.raises(Exception):
        apply_ops(_default_state(), [{"op": "update_item", "id": "missing", "title": "x"}])
