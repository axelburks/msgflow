from msgflow.common.templating import (
    apply_field_rewrite,
    build_tpl_mapping,
    collect_tpl_vars,
    is_value_condition_dict,
    refresh_derived_mapping_fields,
    render_destination,
    render_template,
    render_value,
    select_value_by_condition,
)


def test_render_template_substitutes_values_and_drops_missing_vars():
    rendered = render_template("  {{sender}} -> {{receiver}}: {{missing}}  ", {"sender": "A", "receiver": "B"})

    assert rendered == "A -> B"


def test_build_tpl_mapping_prefers_message_values_over_kwargs():
    mapping = build_tpl_mapping({"sender": "from-msg", "text": None}, sender="from-kwargs", text="from-kwargs")

    assert mapping["sender"] == "from-msg"
    assert mapping["text"] == "from-kwargs"


def test_build_tpl_mapping_does_not_derive_text_from_title_subtitle_body():
    mapping = build_tpl_mapping({"title": "Title", "subtitle": "", "body": "Body"})

    assert mapping["text"] is None


def test_build_tpl_mapping_does_not_derive_trans_from_sender_receiver():
    mapping = build_tpl_mapping({"sender": "Alice", "receiver": "Bob"})

    assert mapping["trans"] is None


def test_build_tpl_mapping_renders_nested_msg_as_compact_json():
    mapping = build_tpl_mapping({"sender": "Alice", "msg": {"rowid": 1, "service": "SMS"}})

    assert mapping["msg"] == '{"rowid":1,"service":"SMS"}'


def test_condition_dict_detection_requires_non_empty_allowed_keys_only():
    assert is_value_condition_dict({"$default": "normal", "$code": "code"})
    assert not is_value_condition_dict({})
    assert not is_value_condition_dict({"$default": "normal", "custom": "bad"})


def test_select_value_by_condition_uses_code_then_default_priority():
    value = {"$default": "normal", "$code": "code"}

    assert select_value_by_condition(value, has_code=True) == "code"
    assert select_value_by_condition(value, has_code=False) == "normal"
    assert select_value_by_condition({"$code": "fallback"}, has_code=False) == "fallback"


def test_collect_tpl_vars_descends_into_payload_json_strings():
    used = collect_tpl_vars(
        {
            "payload": '{"text":"{{text}}","nested":["{{code}}"]}',
            "title": "{{sender}}",
        }
    )

    assert {"text", "code", "sender"} <= used


def test_render_value_parses_payload_json_and_renders_nested_templates():
    rendered = render_value(
        '{"text":"{{text}}","copy":"{{code}}"}',
        {"text": "hello", "code": "123456"},
        has_code=True,
        key_name="payload",
    )

    assert rendered == {"text": "hello", "copy": "123456"}


def test_render_destination_deep_copies_and_exposes_code():
    dest = {
        "channel": "webhook",
        "payload": {
            "title": {"$default": "{{sender}}", "$code": "code {{code}}"},
            "body": "{{text}}",
        },
    }
    msg = {"sender": "alice", "text": "验证码 123456", "code": "123456"}

    rendered = render_destination(dest, msg)

    assert rendered["code"] == "123456"
    assert rendered["payload"] == {"title": "code 123456", "body": "验证码 123456"}
    assert dest["payload"]["title"] == {"$default": "{{sender}}", "$code": "code {{code}}"}


def test_render_destination_refreshes_derived_text_after_body_rewrite():
    dest = {
        "channel": "floating",
        "field_rewrite": {
            "body": [{"pattern": r"\d{6}", "replace": "replaced"}],
        },
        "payload": {
            "body": {"$default": "{{body}}", "$code": "{{text}}"},
        },
    }
    msg = {
        "title": "Bark",
        "subtitle": "中国移动云盘",
        "body": "验证码：125800，请勿泄露",
        "text": "Bark\n中国移动云盘\n验证码：125800，请勿泄露",
        "code": "125800",
    }

    rendered = render_destination(dest, msg)

    assert rendered["payload"]["body"] == "Bark\n中国移动云盘\n验证码：replaced，请勿泄露"


def test_apply_field_rewrite_runs_rules_in_order_per_field():
    mapping = {"text": "phone 13800001234 here", "title": "no change"}
    cfg = {
        "text": [
            {"pattern": r"(\d{3})\d{4}(\d{4})", "replace": r"\1****\2"},
            {"pattern": r"phone", "replace": "ph"},
        ],
    }

    result, touched_fields = apply_field_rewrite(mapping, cfg)

    assert result["text"] == "ph 138****1234 here"
    assert result["title"] == "no change"
    assert touched_fields == {"text"}


def test_apply_field_rewrite_skips_missing_or_non_string_fields():
    mapping = {"text": None, "code": 123}
    cfg = {
        "text": [{"pattern": r"x", "replace": "y"}],
        "code": [{"pattern": r"1", "replace": "9"}],
    }

    result, touched_fields = apply_field_rewrite(mapping, cfg)

    assert result == {"text": None, "code": 123}
    assert touched_fields == set()


def test_apply_field_rewrite_supports_inline_flags():
    mapping = {"body": "Hello WORLD"}
    cfg = {"body": [{"pattern": r"(?i)world", "replace": "earth"}]}

    result, touched_fields = apply_field_rewrite(mapping, cfg)

    assert result["body"] == "Hello earth"
    assert touched_fields == {"body"}


def test_apply_field_rewrite_returns_input_when_cfg_empty():
    mapping = {"text": "hi"}

    result, touched_fields = apply_field_rewrite(mapping, None)
    assert result is mapping
    assert touched_fields == set()

    result, touched_fields = apply_field_rewrite(mapping, {})
    assert result is mapping
    assert touched_fields == set()


def test_refresh_derived_mapping_fields_recomputes_only_affected_fields():
    mapping = {
        "sender": "Alice",
        "receiver": "Bob",
        "title": "Title",
        "subtitle": "Subtitle",
        "body": "Body",
        "text": "stale text",
        "trans": "stale trans",
    }

    refreshed = refresh_derived_mapping_fields(mapping, touched_fields={"body"})

    assert refreshed["text"] == "Title\nSubtitle\nBody"
    assert refreshed["trans"] == "stale trans"
