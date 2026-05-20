import copy

import pytest

from msgflow.config import Config
from msgflow.config.defaults import CONFIG_TEMPLATE


def test_config_creates_default_template_and_valid_built_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))

    cfg = Config(debug=False)

    assert cfg.config_file_path == str(tmp_path / "config.yaml")
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == CONFIG_TEMPLATE
    assert cfg.built_cfg["source"] == "msgflow"
    assert cfg.built_cfg["sms"]["rules"] == []
    assert cfg.built_cfg["alarm"]["rules"] == []


def test_config_builds_kind_specific_destinations_with_unique_names(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        """
target:
  mac:
    channel: notification
sms:
  rules:
    - name_mark: code
      filters:
        - type: selector
          match:
            code: true
      destinations:
        - target: mac
          name_mark: local
notify:
  rules:
    - name_mark: important
      filters:
        - type: and
          match:
            title: ".*"
      destinations:
        - target: mac
ipn:
  rules:
    - name_mark: mirrored
      filters:
        - type: selector
          match:
            text: true
      destinations:
        - target: mac
alarm:
  rules:
    - name_mark: errors
      filters:
        - type: selector
          match:
            error: true
      destinations:
        - target: mac
""",
        encoding="utf-8",
    )

    cfg = Config(debug=False)

    assert cfg.built_cfg["sms"]["rules"][0]["destinations"][0]["name_mark"] == "sms_code_local"
    assert cfg.built_cfg["notify"]["rules"][0]["destinations"][0]["name_mark"] == "notify_important_mac"
    assert cfg.built_cfg["ipn"]["rules"][0]["destinations"][0]["name_mark"] == "ipn_mirrored_mac"
    assert cfg.built_cfg["alarm"]["rules"][0]["destinations"][0]["name_mark"] == "alarm_errors_mac"
    for key in ("kinds"):
        assert key not in cfg.built_cfg["sms"]["rules"][0]["destinations"][0]


def test_config_rejects_unknown_template_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        """
target:
  mac:
    channel: notification
    payload:
      title: "{{not_allowed}}"
      body: "body"
alarm:
  rules:
    - name_mark: errors
      destinations:
        - target: mac
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown tpl vars"):
        Config(debug=False)


def test_config_rejects_duplicate_destination_names(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        """
target:
  mac:
    channel: notification
sms:
  rules:
    - name_mark: code
      destinations:
        - target: mac
          name_mark: dup
        - target: mac
          name_mark: dup
""",
        encoding="utf-8",
    )

    with pytest.raises(Exception, match="duplicate destination name_mark"):
        Config(debug=False)


def test_config_allows_partial_kind_runtime_before_build_and_merges_root_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        """
target:
  mac:
    channel: notification
sms:
  runtime:
    history_mode: replay
  rules:
    - name_mark: code
      destinations:
        - target: mac
""",
        encoding="utf-8",
    )

    cfg = Config(debug=False)

    assert cfg.effective_cfg["sms"]["runtime"] == {"history_mode": "replay"}
    assert cfg.built_cfg["sms"]["runtime"]["history_mode"] == "replay"
    assert cfg.built_cfg["sms"]["runtime"]["check_interval"] == cfg.built_cfg["runtime"]["check_interval"]
    assert cfg.built_cfg["sms"]["runtime"]["retention"] == cfg.built_cfg["runtime"]["retention"]


def test_config_allows_missing_kind_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        """
target:
  mac:
    channel: notification
sms:
  rules:
    - name_mark: code
      destinations:
        - target: mac
""",
        encoding="utf-8",
    )

    cfg = Config(debug=False)

    assert cfg.effective_cfg["ipn"] == {"runtime": {}, "rules": []}
    assert cfg.effective_cfg["notify"] == {"runtime": {}, "rules": []}
    assert cfg.effective_cfg["alarm"] == {"runtime": {}, "rules": []}
    assert cfg.built_cfg["notify"]["rules"] == []
    assert cfg.built_cfg["alarm"]["rules"] == []
    assert cfg.built_cfg["ipn"]["rules"] == []


def test_resolve_destination_applies_channel_kind_target_and_destination_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    cfg = Config(debug=False)
    cfg.effective_cfg = copy.deepcopy(cfg.default_cfg)
    cfg.effective_cfg["target"] = {
        "bark": {
            "channel": "bark",
            "url": "https://example.test",
            "payload": {"title": "target", "body": "target-body"},
        }
    }

    resolved = cfg._resolve_destination(
        {"target": "bark", "payload": {"title": "dest", "body": "dest-body"}},
        kind="notify",
    )

    assert resolved["channel"] == "bark"
    assert resolved["url"] == "https://example.test"
    assert resolved["name_mark"] == "bark"
    assert resolved["payload"]["title"] == "dest"
    assert resolved["payload"]["body"] == "dest-body"
    assert "copy" in resolved["payload"]
    assert "kinds" not in resolved


def test_resolve_destination_applies_kinds_overlay_and_strips_it(monkeypatch, tmp_path):
    monkeypatch.setenv("MSGFLOW_CONFIG_DIR", str(tmp_path))
    cfg = Config(debug=False)
    cfg.effective_cfg = copy.deepcopy(cfg.default_cfg)
    cfg.effective_cfg["target"] = {
        "bark": {
            "channel": "bark",
            "url": "https://example.test",
        }
    }

    resolved = cfg._resolve_destination({"target": "bark"}, kind="alarm")

    assert resolved["payload"]["title"] == "{{source}}: {{error}}"
    assert "kinds" not in resolved
