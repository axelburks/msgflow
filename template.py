import copy
from typing import Any, Optional
import regex

from utils import try_parse_json

# Template variables are written as {{name}} and matched with this regex.
TPL_VAR_PATTERN = r"\{\{(\w+)\}\}"
# Allowed "conditional" keys for a value that varies by context (normal/code/alarm).
ALLOWED_COND_KEYS = ("$default", "$code", "$alarm")


def render_template(template: Any, mapping: Optional[dict[str, Any]]) -> str:
    # Render a single string template by substituting {{var}} occurrences
    # with the corresponding value from `mapping`. Missing vars render as
    # empty strings so partial messages never include a raw "{{...}}" token.
    if not template:
        return ''
    mapping = mapping or {}
    template_str = str(template)

    def _repl(m: regex.Match) -> str:
        key = str(m.group(1)).strip()
        value = mapping.get(key)
        return '' if value is None else str(value)

    rendered = regex.sub(TPL_VAR_PATTERN, _repl, template_str)
    rendered = rendered.strip()
    return rendered


def build_tpl_mapping(msg: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    # Build the var -> value mapping used by `render_template`.
    # Pre-declare every well-known key so `ALLOWED_MATCH_TPL_VARS` reflects
    # the full set of supported variables (see module footer).
    mapping = {
        "sender": msg.get('sender'),
        "receiver": msg.get('receiver'),
        "text": msg.get('text'),
        "timestamp": msg.get('timestamp'),
        "time_str": msg.get('time_str'),
        "msg": msg.get('msg'),
        "code": msg.get('code'),
        "source": msg.get('source'),
        "title": msg.get('title'),
        "subtitle": msg.get('subtitle'),
        "body": msg.get('body'),
        "error": kwargs.get('error'),
        "traceback": kwargs.get('traceback'),
    }
    # Extra kwargs become additional template vars, but never override an
    # already-present non-None value (so msg.sender beats kwargs["sender"]).
    for key, value in kwargs.items():
        if key in mapping and mapping[key] is not None:
            continue
        mapping[key] = value
    return mapping


def is_value_condition_dict(value: Any) -> bool:
    # True iff `value` is a non-empty dict whose keys are ALL in ALLOWED_COND_KEYS
    # (i.e. a conditional value like {"$default": ..., "$code": ..., "$alarm": ...}).
    if not isinstance(value, dict) or not value:
        return False
    return all(k in ALLOWED_COND_KEYS for k in value.keys())


def select_value_by_condition(value_dict: dict[str, Any], has_code: bool, is_alarm: bool) -> Any:
    # Choose which branch of a conditional value to use based on runtime context.
    # Priority: alarm -> code -> default -> first available key.
    if is_alarm and "$alarm" in value_dict:
        return value_dict["$alarm"]
    if has_code and "$code" in value_dict:
        return value_dict["$code"]
    if "$default" in value_dict:
        return value_dict["$default"]
    for _, v in value_dict.items():
        return v
    return None


def collect_tpl_vars(value: Any, key_name: Optional[str] = None) -> set[str]:
    # Recursively walk `value` and return every template variable name used.
    # Used at config-load time to reject typo'd {{vars}}.
    if is_value_condition_dict(value):
        used: set[str] = set()
        for v in value.values():
            used |= collect_tpl_vars(v, key_name=key_name)
        return used

    if isinstance(value, dict):
        used = set()
        for k, v in value.items():
            used |= collect_tpl_vars(v, key_name=str(k))
        return used

    if isinstance(value, list):
        used = set()
        for v in value:
            used |= collect_tpl_vars(v, key_name=key_name)
        return used

    if isinstance(value, str):
        used = set(regex.findall(TPL_VAR_PATTERN, value))
        # `payload` strings may contain an embedded JSON object (e.g. Lark
        # interactive cards). Parse and descend to capture nested template vars.
        if key_name == "payload":
            parsed = try_parse_json(value)
            if isinstance(parsed, (dict, list)):
                used |= collect_tpl_vars(parsed, key_name=None)
        return used

    return set()


def render_value(
    value: Any,
    mapping: dict[str, Any],
    has_code: bool,
    is_alarm: bool,
    key_name: Optional[str] = None,
) -> Any:
    # Recursive counterpart to `collect_tpl_vars`: actually substitute values.
    # Conditional dicts are collapsed first, then primitives are rendered.
    if is_value_condition_dict(value):
        chosen = select_value_by_condition(value, has_code=has_code, is_alarm=is_alarm)
        return render_value(chosen, mapping, has_code=has_code, is_alarm=is_alarm, key_name=key_name)

    if isinstance(value, dict):
        rendered = {}
        for k, v in value.items():
            rendered[k] = render_value(v, mapping, has_code=has_code, is_alarm=is_alarm, key_name=k)
        return rendered

    if isinstance(value, list):
        return [render_value(v, mapping, has_code=has_code, is_alarm=is_alarm, key_name=key_name) for v in value]

    if isinstance(value, str):
        # Parse-and-re-render when the string is actually a JSON blob under
        # `payload`, so template substitution runs against the structured form
        # (safer escaping, preserves types for downstream channels).
        if key_name == "payload":
            parsed = try_parse_json(value)
            if isinstance(parsed, (dict, list)):
                return render_value(parsed, mapping, has_code=has_code, is_alarm=is_alarm, key_name=None)
        return render_template(value, mapping)

    return value


def render_destination(
    dest: dict[str, Any],
    msg: Optional[dict[str, Any]] = None,
    is_alarm: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    # Render an entire destination template against `msg`. Returns a deep-copied
    # fully-resolved destination ready for the channel notifier.
    if msg is None:
        msg = {}
    mapping = build_tpl_mapping(msg, **kwargs)
    rendered_dest = copy.deepcopy(dest)
    # Surface `code` at the top level so channel notifiers (e.g. tgbot's
    # HTML escaping path) can access it without re-parsing the payload.
    rendered_dest["code"] = msg.get('code')
    has_code = bool(msg.get('code'))
    rendered_dest = render_value(rendered_dest, mapping, has_code=has_code, is_alarm=is_alarm)
    return rendered_dest


# Keys exported by `build_tpl_mapping({})` = the full allowlist of template
# variable names. config.py uses it to reject unknown {{vars}} at load time.
ALLOWED_MATCH_TPL_VARS = tuple(build_tpl_mapping({}).keys())
