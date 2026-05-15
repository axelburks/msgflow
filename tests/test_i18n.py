from msgflow.ui import i18n


class FakeDefaults:
    def __init__(self):
        self.values = {}

    def stringForKey_(self, key):
        return self.values.get(key)

    def setObject_forKey_(self, value, key):
        self.values[key] = value

    def synchronize(self):
        return True


def test_i18n_defaults_to_english(monkeypatch):
    defaults = FakeDefaults()
    monkeypatch.setattr(i18n, "_user_defaults", lambda: defaults)

    assert i18n.current_language() == "en"
    assert i18n.t("menu.language") == "Language"
    assert i18n.t("language.restart_title") == "Restart msgflow to apply language?"


def test_i18n_persists_selected_language(monkeypatch):
    defaults = FakeDefaults()
    monkeypatch.setattr(i18n, "_user_defaults", lambda: defaults)

    assert i18n.set_language("zh-CN") == "zh-CN"
    assert defaults.values[i18n.LANGUAGE_DEFAULTS_KEY] == "zh-CN"
    assert i18n.current_language() == "zh-CN"
    assert i18n.t("menu.language") == "语言"
    assert i18n.t("language.restart_title") == "重启 msgflow 以应用语言？"


def test_i18n_rejects_unknown_language(monkeypatch):
    defaults = FakeDefaults()
    monkeypatch.setattr(i18n, "_user_defaults", lambda: defaults)

    assert i18n.set_language("fr") == "en"
    assert i18n.current_language() == "en"


def test_i18n_uses_explicit_default_for_missing_key(monkeypatch):
    defaults = FakeDefaults()
    monkeypatch.setattr(i18n, "_user_defaults", lambda: defaults)

    assert i18n.t("runtime_status.restarting", _default="restarting") == "restarting"


def test_query_help_text_uses_selected_language_and_fields(monkeypatch):
    defaults = FakeDefaults()
    monkeypatch.setattr(i18n, "_user_defaults", lambda: defaults)

    assert "Available fields" in i18n.query_help_text("text, code")
    assert "text, code" in i18n.query_help_text("text, code")

    i18n.set_language("zh-CN")
    assert "可用字段" in i18n.query_help_text("text, code")
    assert "text, code" in i18n.query_help_text("text, code")


def test_filter_and_runtime_status_keys_use_selected_language(monkeypatch):
    defaults = FakeDefaults()
    monkeypatch.setattr(i18n, "_user_defaults", lambda: defaults)

    assert i18n.t("filter.sms") == "SMS"
    assert i18n.t("runtime_status.error") == "error"
    assert i18n.t("runtime_status.running") == "running"
    assert i18n.t("runtime_status.paused") == "paused"

    i18n.set_language("zh-CN")
    assert i18n.t("filter.sms") == "短信"
    assert i18n.t("runtime_status.error") == "错误"
    assert i18n.t("runtime_status.running") == "运行中"
    assert i18n.t("runtime_status.paused") == "已暂停"
    assert i18n.t("runtime_status.unknown") == "未知"
