"""The main Agent's Content Desk tool builds bounded ops, not page writes."""

from src.tools.content_desk.tool import ContentDeskArgs, _build_ops, _summary


def _args(**overrides):
    action = overrides.pop("action", "list")
    return ContentDeskArgs(action=action, **overrides)


def test_add_builds_an_add_item_op():
    ops = _build_ops(_args(action="add", title="选题", body="正文", platform="小红书"))
    assert ops == [{"op": "add_item", "title": "选题", "body": "正文", "platform": "小红书"}]


def test_update_keeps_only_given_fields():
    ops = _build_ops(_args(action="update", item_id="it_1", title="新标题"))
    assert ops == [{"op": "update_item", "id": "it_1", "title": "新标题"}]


def test_save_draft_is_an_update_with_a_draft_and_status():
    ops = _build_ops(_args(action="save_draft", item_id="it_1", text="初稿"))
    assert ops == [{"op": "update_item", "id": "it_1", "draft": {"body": "初稿", "model": "LangAlpha"}, "status": "draft"}]


def test_summary_lists_ids_and_statuses():
    text = _summary({"items": [{"id": "it_1", "title": "标题", "status": "idea"}]})
    assert "it_1" in text and "标题" in text


def test_update_requires_an_id():
    try:
        _build_ops(_args(action="update", title="x"))
    except ValueError as exc:
        assert "item_id" in str(exc)
    else:
        raise AssertionError("expected a refusal")
