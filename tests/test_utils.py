import json
import subprocess
import time
from pathlib import Path

import pytest

from msgflow.common import utils


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


def _notify_text_from_item(item):
    if item.get("text"):
        return item["text"]
    parts = [item.get("title") or "", item.get("subtitle") or "", item.get("body") or ""]
    return "\n".join(part for part in parts if part)


def _load_code_fixture_cases(kind):
    path = FIXTURE_ROOT / kind / f"{kind}.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for index, item in enumerate(items):
        if kind in ("notify", "ipn"):
            text = _notify_text_from_item(item)
        else:
            text = item.get("text") or ""
        expected = item.get("code_expected")
        case_id = f"{kind}[{index}]={expected or 'None'}"
        cases.append(pytest.param(text, expected, id=case_id))
    return cases


def test_deep_merge_dicts_recursively_merges_and_overrides_scalars():
    merged = utils.deep_merge_dicts(
        {"channel": {"webhook": {"method": "POST", "timeout": 3}}, "rules": [1]},
        {"channel": {"webhook": {"timeout": 10}}, "rules": [2]},
    )

    assert merged == {"channel": {"webhook": {"method": "POST", "timeout": 10}}, "rules": [2]}


def test_deep_merge_dicts_treats_non_dict_inputs_as_empty():
    assert utils.deep_merge_dicts(None, {"a": 1}) == {"a": 1}
    assert utils.deep_merge_dicts({"a": 1}, None) == {"a": 1}


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param('{"a": 1}', {"a": 1}, id="合法 JSON"),
        pytest.param("not-json", None, id="非法 JSON"),
        pytest.param({"a": 1}, None, id="非字符串"),
    ],
)
def test_try_parse_json(value, expected):
    assert utils.try_parse_json(value) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        pytest.param("您的验证码是 123456，请勿泄露", "123456", id="中文验证码"),
        pytest.param("Verification code: 987654, ignore https://example.com/123456", "987654", id="英文验证码并忽略 URL"),
        pytest.param("尾号1234的银行卡消费，验证码 1122", "1122", id="忽略尾号数字"),
        pytest.param("普通通知 123456 没有码字样", None, id="无验证码关键字"),
        pytest.param("", None, id="空文本"),
    ],
)
def test_get_code_from_text(text, expected):
    assert utils.get_code_from_text(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    _load_code_fixture_cases("sms") + _load_code_fixture_cases("notify") + _load_code_fixture_cases("ipn"),
)
def test_get_code_from_text_matches_fixture_expected_codes(text, expected):
    assert utils.get_code_from_text(text) == expected


def test_get_app_name_uses_positive_cache(monkeypatch):
    utils._APP_NAME_CACHE.clear()
    utils._APP_NAME_MISS.clear()
    calls = []

    def fake_lookup(bundle_id):
        calls.append(bundle_id)
        return "/Applications/Fake.app"

    monkeypatch.setattr(utils, "_app_path_from_mdfind", fake_lookup)

    assert utils.get_app_name("com.example.fake") == "Fake"
    assert utils.get_app_name("com.example.fake") == "Fake"
    assert calls == ["com.example.fake"]


def test_get_app_name_uses_negative_cache(monkeypatch):
    utils._APP_NAME_CACHE.clear()
    utils._APP_NAME_MISS.clear()
    calls = []
    monkeypatch.setattr(utils, "_app_path_from_mdfind", lambda bundle_id: calls.append(bundle_id) or None)

    assert utils.get_app_name("com.example.missing") is None
    assert utils.get_app_name("com.example.missing") is None
    assert calls == ["com.example.missing"]


def test_app_path_from_mdfind_returns_first_result(monkeypatch):
    class FakeCompleted:
        stdout = "/Applications/Fake.app\n/Applications/Other.app\n"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompleted())

    assert utils._app_path_from_mdfind("com.example.fake") == "/Applications/Fake.app"


def test_get_app_name_retries_after_negative_cache_ttl(monkeypatch):
    utils._APP_NAME_CACHE.clear()
    utils._APP_NAME_MISS.clear()
    utils._APP_NAME_MISS["com.example.old"] = time.time() - utils._APP_NAME_MISS_TTL - 1
    monkeypatch.setattr(utils, "_app_path_from_mdfind", lambda _bundle_id: "/Applications/NowFound.app")

    assert utils.get_app_name("com.example.old") == "NowFound"
