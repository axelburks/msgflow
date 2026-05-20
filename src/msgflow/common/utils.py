import json, datetime, os, re, subprocess, time
from typing import Any, Optional
import regex
import logging

logger = logging.getLogger(__name__)

# Offset between Mac absolute time (seconds since 2001-01-01 UTC) and the
# Unix epoch. Shared by any flow whose source DB stores timestamps in
# Mac-abs-time (e.g. chat.db's `message.date`, usernoted's `delivered_date`).
MAC_EPOCH_OFFSET = 978307200

# In-process caches for bundle-id -> app-name lookups. `mdfind` is relatively
# expensive, so we cache positive hits forever and cache misses for TTL seconds
# to avoid repeatedly spawning mdfind for apps not installed on this machine.
_APP_NAME_CACHE: dict[str, str] = {}
_APP_NAME_MISS: dict[str, float] = {}
_APP_NAME_MISS_TTL = 300
_APP_NAME_MDFIND_TIMEOUT = 5


def get_app_name(bundle_id: Optional[str]) -> Optional[str]:
    # Resolve a macOS bundle identifier (e.g. "com.apple.MobileSMS") to the
    # app's display name ("Messages") by querying Spotlight via `mdfind`.
    # Returns None when the bundle id is missing or can't be resolved.
    if not bundle_id:
        return None

    cached = _APP_NAME_CACHE.get(bundle_id)
    if cached is not None:
        return cached

    # Respect a short negative cache window so unknown bundle ids don't spawn
    # `mdfind` on every notification.
    last_miss = _APP_NAME_MISS.get(bundle_id)
    if last_miss is not None and (time.time() - last_miss) < _APP_NAME_MISS_TTL:
        return None

    app_path = _app_path_from_mdfind(bundle_id)
    if app_path is None:
        _APP_NAME_MISS[bundle_id] = time.time()
        return None

    name = os.path.splitext(os.path.basename(app_path))[0]
    _APP_NAME_CACHE[bundle_id] = name
    _APP_NAME_MISS.pop(bundle_id, None)
    return name


def _app_path_from_mdfind(bundle_id: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ['mdfind', f'kMDItemCFBundleIdentifier == "{bundle_id}"'],
            capture_output=True, text=True, timeout=_APP_NAME_MDFIND_TIMEOUT
        )
        out = result.stdout.strip().splitlines()
        if out:
            return out[0]
        logger.warning(
            "mdfind returned empty for %r (rc=%s, stderr=%r)",
            bundle_id,
            result.returncode,
            result.stderr,
        )
    except Exception as e:
        logger.warning("get app name for %r error: %s", bundle_id, e)
    return None


def format_ts(ts: Any) -> str:
    # Format a POSIX timestamp as "YYYY-MM-DD HH:MM:SS[.ffffff]".
    # Microseconds are included only if the input has a fractional part, so
    # whole-second values stay compact in logs/record files.
    try:
        ts_float = float(ts)
        dt = datetime.datetime.fromtimestamp(ts_float)
        if ts_float == int(ts_float):
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')
    except Exception:
        return ''


def deep_merge_dicts(low_priority: Any, high_priority: Any) -> dict[str, Any]:
    # Recursively merge two dicts. Values from `high_priority` win on conflicts;
    # nested dicts merge recursively, scalars/lists are replaced wholesale.
    # Non-dict inputs are coerced to empty dicts so callers don't have to.
    if not isinstance(low_priority, dict):
        low_priority = {}
    if not isinstance(high_priority, dict):
        high_priority = {}
    merged = dict(low_priority)
    for key, value in high_priority.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def try_parse_json(value: Any) -> Any:
    # Best-effort JSON parse. Returns the parsed value on success, None
    # otherwise. Only strings are considered so non-string inputs short-circuit.
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def get_code_from_text(text: Optional[str]) -> Optional[str]:
    # Extract a verification/one-time code from a free-form message text.
    # Strategy:
    #   1) Scrub URLs and newlines so their digits don't pollute the captcha
    #      candidate set.
    #   2) Find a "code keyword" (验证码 / verification code / ...).
    #   3) Find all 4-8 digit candidates that look like captchas
    #      (excluding phone-number tails, service numbers, etc.).
    #   4) Pick the candidate closest to the keyword, within 80 chars.
    code: Optional[str] = None
    if not text:
        return None

    # Regex matching words that typically introduce a verification code.
    pattern_flags = r"(?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode)"

    # Regex matching captcha-looking numeric groups of 4-8 digits, with
    # lookbehind/lookahead to reject phone numbers and service hotlines.
    pattern_captchas = r"(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)"

    # Strip URLs and newlines so the distance calculation in step 4 is not
    # inflated by unrelated text.
    text_escaped = regex.sub(r'((https?|ftp|file):\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|$!:,.;]*[A-Z0-9+&@#\/%=~_|$]|\n', ' ', text, flags=regex.I)

    match_flags = regex.search(pattern_flags, text_escaped, flags=regex.I)
    matches_captchas = regex.findall(pattern_captchas, text_escaped)

    if match_flags and matches_captchas:
        max_distance = 80
        flag_index = text_escaped.find(match_flags.group())
        # Pick the captcha whose position is closest to the keyword; reject if
        # farther than `max_distance` chars away (likely unrelated digits).
        closest_captcha = min(matches_captchas, key=lambda x: abs(text_escaped.find(x[1]) - flag_index))[1]
        if abs(text_escaped.find(closest_captcha) - flag_index) <= max_distance:
            code = closest_captcha

    return code


def extract_code(text: str, code_pattern_cfg: Optional[dict[str, Any]]) -> Optional[str]:
    # User-defined verification-code extraction.
    # When `code_pattern_cfg` is None (user didn't configure it at all), fall
    # straight through to the built-in detector — no config should mean "use
    # the default behaviour", not "disable extraction entirely".
    #
    # When the user *has* configured rules, try each rule in order; the first
    # match wins. If no rule matches, `fallback_to_builtin` decides whether
    # the built-in detector runs as a safety net.
    if code_pattern_cfg is None:
        return get_code_from_text(text)
    rules = code_pattern_cfg.get("rules")
    if not rules:
        return get_code_from_text(text)
    for rule in rules:
        pattern = rule.get("pattern")
        compiled = re.compile(pattern)
        m = compiled.search(text)
        if not m:
            continue
        group = rule.get("group")
        try:
            if group is None:
                value = m.group(0)
            else:
                value = m.group(group)
        except (IndexError, re.error):
            continue
        if value:
            return value
    if code_pattern_cfg.get("fallback_to_builtin"):
        return get_code_from_text(text)
    return None


if __name__ == '__main__':
    # Lightweight self-test harness: runs `get_code_from_text` against the
    # sample data in ../tests/fixtures, comparing the
    # extracted code with the `code_expected` field on each sample.
    from .paths import test_fixture_path

    def _load_json(path: str) -> Optional[Any]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] failed to load {path}: {e}")
            return None

    def _build_text_for_notify(msg: dict[str, Any]) -> str:
        # Notify samples may store the text across title/subtitle/body; match
        # runtime behavior by concatenating the non-empty pieces.
        if msg.get("text"):
            return msg["text"]
        parts = [msg.get("title") or '', msg.get("subtitle") or '', msg.get("body") or '']
        return "\n".join(p for p in parts if p)

    def _run_cases(label: str, msgs: Optional[list[dict[str, Any]]], text_builder) -> tuple[int, int]:
        if not msgs:
            print(f"--- {label}: no data, skipped ---")
            return 0, 0
        total = len(msgs)
        failed: list[tuple[int, str, Any, Any]] = []
        for i, msg in enumerate(msgs):
            text = text_builder(msg)
            expected = msg.get("code_expected")
            got = get_code_from_text(text)
            if got != expected:
                failed.append((i, text, expected, got))
        print(f"--- {label}: {total - len(failed)}/{total} passed ---")
        for i, text, expected, got in failed:
            print(f"  [#{i}] expected={expected!r}, got={got!r}")
            print(f"       text: {text}")
            print("")
        return total, len(failed)

    sms_total, sms_fail = _run_cases(
        "sms (tests/fixtures/sms/sms.json)",
        _load_json(str(test_fixture_path("sms", "sms.json"))),
        lambda m: m.get("text") or '',
    )
    notify_total, notify_fail = _run_cases(
        "notify (tests/fixtures/notify/notify.json)",
        _load_json(str(test_fixture_path("notify", "notify.json"))),
        _build_text_for_notify,
    )

    total = sms_total + notify_total
    fail = sms_fail + notify_fail
    print(f"=== summary: {total - fail}/{total} passed, {fail} failed ===")
