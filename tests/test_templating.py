from msgflow.common.templating import (
    build_tpl_mapping,
    collect_tpl_vars,
    is_value_condition_dict,
    render_destination,
    render_template,
    render_value,
    select_value_by_condition,
)


def test_render_template_substitutes_values_and_drops_missing_vars():
    rendered = render_template("  {{sender}} -> {{receiver}}: {{missing}}  ", {"sender": "A", "receiver": "B"})

    assert rendered == "A -> B:"


def test_build_tpl_mapping_prefers_message_values_over_kwargs():
    mapping = build_tpl_mapping({"sender": "from-msg", "text": None}, sender="from-kwargs", text="from-kwargs")

    assert mapping["sender"] == "from-msg"
    assert mapping["text"] == "from-kwargs"


def test_condition_dict_detection_requires_non_empty_allowed_keys_only():
    assert is_value_condition_dict({"$default": "normal", "$code": "code"})
    assert not is_value_condition_dict({})
    assert not is_value_condition_dict({"$default": "normal", "custom": "bad"})


def test_select_value_by_condition_uses_alarm_then_code_then_default_priority():
    value = {"$default": "normal", "$code": "code", "$alarm": "alarm"}

    assert select_value_by_condition(value, has_code=True, is_alarm=True) == "alarm"
    assert select_value_by_condition(value, has_code=True, is_alarm=False) == "code"
    assert select_value_by_condition(value, has_code=False, is_alarm=False) == "normal"
    assert select_value_by_condition({"$code": "fallback"}, has_code=False, is_alarm=False) == "fallback"


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
        is_alarm=False,
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
