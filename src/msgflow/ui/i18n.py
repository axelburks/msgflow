from Foundation import NSUserDefaults


DEFAULT_LANGUAGE = "en"
LANGUAGE_DEFAULTS_KEY = "msgflow.ui.language"
SUPPORTED_LANGUAGES = ("en", "zh-CN")
LANGUAGE_NAMES = {
    "en": "English",
    "zh-CN": "中文",
}


TRANSLATIONS = {
    "en": {
        "about.author": "Author",
        "about.open_github": "Open GitHub",
        "about.version": "Version",
        "action.apply": "Apply",
        "action.cancel": "Cancel",
        "action.close": "Close",
        "action.continue": "Continue",
        "action.delete": "Delete",
        "action.grant": "Grant",
        "action.later": "Later",
        "action.ok": "OK",
        "action.paste": "Paste",
        "action.quit": "Quit",
        "action.reload": "Reload",
        "action.rematch": "Rematch",
        "action.resend": "Resend",
        "action.restart": "Restart",
        "action.type": "Type",
        "alert.delete_detail": "This permanently removes the selected run record from local history.",
        "alert.delete_title": "Delete selected run?",
        "alert.edit_cursor_detail": "Changes stay local in this sheet until you click Apply.",
        "alert.edit_cursor_title": "Edit Cursor",
        "alert.error_title": "Error",
        "alert.no_cursor_destinations": "No cursor destinations found.",
        "alert.no_destinations": "No destinations available in the selected run.",
        "alert.no_selection": "Please select a run first.",
        "alert.rematch_detail": "This will match the original message with the current runtime config and send it again.",
        "alert.rematch_title": "Rematch selected message?",
        "alert.resend_detail": "The selected destination will be resent with the current runtime config.",
        "alert.resend_title": "Select destination to resend",
        "config.built_title": "Built Config",
        "config.reload_error": "Failed to load built config: {error}",
        "cursor.column.cursor": "Cursor",
        "cursor.column.destination": "Destination",
        "cursor.column.kind": "Kind",
        "cursor.empty_error": "cursor for '{destination}' ({kind}) cannot be empty",
        "filter.all_kind": "All",
        "filter.all_title": "{prefix}: All",
        "filter.ipn": "IPN",
        "filter.notify": "Notify",
        "filter.placeholder": "Filter records - hover ? for syntax. Press Enter to apply.",
        "filter.query_help_accessibility": "Query syntax help",
        "filter.sms": "SMS",
        "filter.status": "Status",
        "filter.trigger": "Trigger",
        "main.close_window": "Close Window",
        "main.copy": "Copy",
        "main.cut": "Cut",
        "main.edit": "Edit",
        "main.hide": "Hide msgflow",
        "main.hide_others": "Hide Others",
        "main.minimize": "Minimize",
        "main.paste": "Paste",
        "main.quit": "Quit msgflow",
        "main.redo": "Redo",
        "main.select_all": "Select All",
        "main.show_all": "Show All",
        "main.undo": "Undo",
        "main.window": "Window",
        "menu.about": "About msgflow",
        "menu.continue_setup": "Continue Setup",
        "menu.debug_mode": "Debug Mode",
        "menu.language": "Language",
        "menu.launch_at_login": "Launch at Login",
        "menu.open_config_folder": "Open Config Folder",
        "menu.open_window": "Open Window",
        "menu.pause": "Pause",
        "menu.permissions": "Permissions...",
        "menu.quit": "Quit",
        "menu.reload_config": "Reload Config",
        "menu.start": "Start",
        "menu.status": "Status: {status}",
        "menu.status_setup_required": "Status: Setup Required",
        "menu.status_unavailable": "Status: unavailable",
        "language.restart_detail": "msgflow needs to restart before the new language takes effect.",
        "language.restart_title": "Restart msgflow to apply language?",
        "runtime_status.error": "error",
        "runtime_status.paused": "paused",
        "runtime_status.running": "running",
        "runtime_status.unknown": "unknown",
        "query.help": (
            "About\n"
            "  Filter the run-record list with a query DSL.\n"
            "  Bare words search the `text` field. Field clauses use `field:value`.\n"
            "  Spaces mean AND; use parentheses to group conditions.\n"
            "\n"
            "Boolean logic\n"
            "  a b  -  a AND b\n"
            "  a | b, a OR b  -  a OR b\n"
            "  -a, !a, NOT a  -  exclude a\n"
            "  kind:sms (status:failed | status:success)  -  grouped logic\n"
            "\n"
            "Field operators\n"
            "  text:hello  -  contains hello\n"
            "  text:=hello  -  exact equals hello\n"
            "  text:~hello.*  -  regex match\n"
            "  text:!hello  -  does not contain hello\n"
            "  text:!=hello  -  not equals hello\n"
            "  text:!~^debug  -  regex does not match\n"
            "\n"
            "Field groups\n"
            "  status:(failed | success)  -  same as status:failed OR status:success\n"
            "  text:(\"hello world\" | 验证码)  -  OR values in the same field\n"
            "  status:(=failed | !=success | !~debug)  -  operator shorthand\n"
            "\n"
            "Quotes and escaping\n"
            "  Quote spaces or DSL symbols: text:\"a | b\", text:'hello (test)'\n"
            "  Bare values use \\ to escape one char: alice\\ bob, a\\|b\n"
            "  Quote regex for readability: code:~'\\d+', text:~'(验证码|code)\\d{{6}}'\n"
            "\n"
            "Available fields (all operators above supported)\n"
            "  {fields}\n"
            "\n"
            "Examples\n"
            "  hello  -  search hello in text\n"
            "  sender:+86 status:failed  -  sender has +86 AND run failed\n"
            "  kind:sms -(sender:bot | text:debug)  -  sms excluding bot/debug\n"
            "  trigger:!auto code:~'\\d{{6}}'  -  non-auto runs with a 6-digit code\n"
            "  trace:'\"dest\":\"bark_axel\"'  -  trace json mentions dest bark_axel\n"
            "  msg:!~^debug kind:sms  -  sms whose msg does NOT start with debug"
        ),
        "run.created": "Created",
        "run.failed_detail": "Failed to load detail: {error}",
        "run.failed_load": "Failed to load runs: {error}",
        "run.message": "Message",
        "run.message_id": "Message ID",
        "run.no_selection": "No selection",
        "run.run_id": "Run ID",
        "run.status": "Status",
        "run_action.status": "{action} Status: {status}\nRun ID: {run_id}",
        "setup.accessibility_desc": "Allows msgflow to show floating actions and type or paste into other apps.",
        "setup.accessibility_note": "Already enabled but still not granted? Remove the old entry, then click Grant again.",
        "setup.accessibility_title": "Accessibility",
        "setup.checking": "Checking...",
        "setup.full_disk_desc": "Allows msgflow to read Messages and Notifications so it can monitor new items.",
        "setup.full_disk_title": "Full Disk Access",
        "setup.granted": "Granted",
        "setup.needs_permission": "Needs Permission",
        "setup.subtitle": "Grant these permissions, then continue. This screen updates automatically.",
        "setup.title": "Set Up msgflow",
        "setup.window_title": "msgflow Setup",
        "toolbar.config": "Config",
        "toolbar.config_tip": "View the effective built config",
        "toolbar.cursor": "Cursor",
        "toolbar.cursor_tip": "Edit per-kind destination cursors",
        "toolbar.delete": "Delete",
        "toolbar.delete_tip": "Delete the selected run record",
        "toolbar.refresh": "Refresh",
        "toolbar.refresh_tip": "Refresh records",
        "toolbar.rematch": "Rematch",
        "toolbar.rematch_tip": "Rematch selected message and send it again",
        "toolbar.resend": "Resend",
        "toolbar.resend_tip": "Resend the selected run to one destination",
        "toolbar.reset": "Reset",
        "toolbar.reset_tip": "Reset filters",
    },
    "zh-CN": {
        "about.author": "作者",
        "about.open_github": "打开 GitHub",
        "about.version": "版本",
        "action.apply": "应用",
        "action.cancel": "取消",
        "action.close": "关闭",
        "action.continue": "继续",
        "action.delete": "删除",
        "action.grant": "授权",
        "action.later": "稍后",
        "action.ok": "好",
        "action.paste": "粘贴",
        "action.quit": "退出",
        "action.reload": "重新加载",
        "action.rematch": "重新匹配",
        "action.resend": "重发",
        "action.restart": "重启",
        "action.type": "输入",
        "alert.delete_detail": "这会从本地历史中永久删除选中的运行记录。",
        "alert.delete_title": "删除选中的运行记录？",
        "alert.edit_cursor_detail": "修改会先保留在此面板中，点击“应用”后才会生效。",
        "alert.edit_cursor_title": "编辑游标",
        "alert.error_title": "错误",
        "alert.no_cursor_destinations": "没有找到游标目标。",
        "alert.no_destinations": "选中的运行记录中没有可用目标。",
        "alert.no_selection": "请先选择一条运行记录。",
        "alert.rematch_detail": "这会使用当前运行配置重新匹配原始消息并再次发送。",
        "alert.rematch_title": "重新匹配选中的消息？",
        "alert.resend_detail": "将使用当前运行配置重发选中的目标。",
        "alert.resend_title": "选择要重发的目标",
        "config.built_title": "构建后的配置",
        "config.reload_error": "加载构建配置失败：{error}",
        "cursor.column.cursor": "游标",
        "cursor.column.destination": "目标",
        "cursor.column.kind": "类型",
        "cursor.empty_error": "'{destination}' ({kind}) 的游标不能为空",
        "filter.all_kind": "全部",
        "filter.all_title": "{prefix}：全部",
        "filter.ipn": "手机通知",
        "filter.notify": "通知",
        "filter.placeholder": "过滤记录 - 悬停 ? 查看语法。按 Enter 应用。",
        "filter.query_help_accessibility": "查询语法帮助",
        "filter.sms": "短信",
        "filter.status": "状态",
        "filter.trigger": "触发",
        "main.close_window": "关闭窗口",
        "main.copy": "复制",
        "main.cut": "剪切",
        "main.edit": "编辑",
        "main.hide": "隐藏 msgflow",
        "main.hide_others": "隐藏其他应用",
        "main.minimize": "最小化",
        "main.paste": "粘贴",
        "main.quit": "退出 msgflow",
        "main.redo": "重做",
        "main.select_all": "全选",
        "main.show_all": "显示全部",
        "main.undo": "撤销",
        "main.window": "窗口",
        "menu.about": "关于 msgflow",
        "menu.continue_setup": "继续设置",
        "menu.debug_mode": "调试模式",
        "menu.language": "语言",
        "menu.launch_at_login": "开机启动",
        "menu.open_config_folder": "打开配置目录",
        "menu.open_window": "打开窗口",
        "menu.pause": "暂停",
        "menu.permissions": "权限...",
        "menu.quit": "退出",
        "menu.reload_config": "重新加载配置",
        "menu.start": "启动",
        "menu.status": "状态：{status}",
        "menu.status_setup_required": "状态：需要设置",
        "menu.status_unavailable": "状态：不可用",
        "language.restart_detail": "msgflow 需要重启后才会应用新的语言。",
        "language.restart_title": "重启 msgflow 以应用语言？",
        "runtime_status.error": "错误",
        "runtime_status.paused": "已暂停",
        "runtime_status.running": "运行中",
        "runtime_status.unknown": "未知",
        "query.help": (
            "说明\n"
            "  使用查询 DSL 过滤运行记录列表。\n"
            "  普通词会搜索 `text` 字段。字段条件使用 `field:value`。\n"
            "  空格表示 AND；使用括号组合条件。\n"
            "\n"
            "布尔逻辑\n"
            "  a b  -  a AND b\n"
            "  a | b, a OR b  -  a OR b\n"
            "  -a, !a, NOT a  -  排除 a\n"
            "  kind:sms (status:failed | status:success)  -  分组逻辑\n"
            "\n"
            "字段操作符\n"
            "  text:hello  -  包含 hello\n"
            "  text:=hello  -  精确等于 hello\n"
            "  text:~hello.*  -  正则匹配\n"
            "  text:!hello  -  不包含 hello\n"
            "  text:!=hello  -  不等于 hello\n"
            "  text:!~^debug  -  正则不匹配\n"
            "\n"
            "字段分组\n"
            "  status:(failed | success)  -  等同于 status:failed OR status:success\n"
            "  text:(\"hello world\" | 验证码)  -  同一字段的 OR 值\n"
            "  status:(=failed | !=success | !~debug)  -  操作符简写\n"
            "\n"
            "引号与转义\n"
            "  空格或 DSL 符号可加引号：text:\"a | b\", text:'hello (test)'\n"
            "  裸值可用 \\ 转义一个字符：alice\\ bob, a\\|b\n"
            "  为了可读性可给正则加引号：code:~'\\d+', text:~'(验证码|code)\\d{{6}}'\n"
            "\n"
            "可用字段（均支持以上操作符）\n"
            "  {fields}\n"
            "\n"
            "示例\n"
            "  hello  -  在 text 中搜索 hello\n"
            "  sender:+86 status:failed  -  sender 包含 +86 且运行失败\n"
            "  kind:sms -(sender:bot | text:debug)  -  sms 且排除 bot/debug\n"
            "  trigger:!auto code:~'\\d{{6}}'  -  非自动触发且包含 6 位验证码\n"
            "  trace:'\"dest\":\"bark_axel\"'  -  trace json 中包含 dest bark_axel\n"
            "  msg:!~^debug kind:sms  -  msg 不是以 debug 开头的 sms"
        ),
        "run.created": "创建时间",
        "run.failed_detail": "加载详情失败：{error}",
        "run.failed_load": "加载运行记录失败：{error}",
        "run.message": "消息",
        "run.message_id": "消息 ID",
        "run.no_selection": "未选择",
        "run.run_id": "运行 ID",
        "run.status": "状态",
        "run_action.status": "{action} 状态：{status}\n运行 ID：{run_id}",
        "setup.accessibility_desc": "允许 msgflow 显示浮动操作，并向其他应用输入或粘贴内容。",
        "setup.accessibility_note": "已启用但仍未授权？请先移除旧条目，再点击授权。",
        "setup.accessibility_title": "辅助功能",
        "setup.checking": "检查中...",
        "setup.full_disk_desc": "允许 msgflow 读取信息和通知，以便监控新内容。",
        "setup.full_disk_title": "完全磁盘访问权限",
        "setup.granted": "已授权",
        "setup.needs_permission": "需要授权",
        "setup.subtitle": "授予这些权限后继续。此界面会自动刷新。",
        "setup.title": "设置 msgflow",
        "setup.window_title": "msgflow 设置",
        "toolbar.config": "配置",
        "toolbar.config_tip": "查看构建后的有效配置",
        "toolbar.cursor": "游标",
        "toolbar.cursor_tip": "编辑每种类型的目标游标",
        "toolbar.delete": "删除",
        "toolbar.delete_tip": "删除选中的运行记录",
        "toolbar.refresh": "刷新",
        "toolbar.refresh_tip": "刷新记录",
        "toolbar.rematch": "重新匹配",
        "toolbar.rematch_tip": "重新匹配选中的消息并再次发送",
        "toolbar.resend": "重发",
        "toolbar.resend_tip": "将选中的运行记录重发到一个目标",
        "toolbar.reset": "重置",
        "toolbar.reset_tip": "重置过滤器",
    },
}


def normalize_language(language: str | None) -> str:
    if language in SUPPORTED_LANGUAGES:
        return str(language)
    return DEFAULT_LANGUAGE


def _user_defaults():
    return NSUserDefaults.standardUserDefaults()


def current_language() -> str:
    raw_value = _user_defaults().stringForKey_(LANGUAGE_DEFAULTS_KEY)
    return normalize_language(str(raw_value) if raw_value else None)


def set_language(language: str) -> str:
    normalized = normalize_language(language)
    defaults = _user_defaults()
    defaults.setObject_forKey_(normalized, LANGUAGE_DEFAULTS_KEY)
    defaults.synchronize()
    return normalized


def t(key: str, **kwargs) -> str:
    language = current_language()
    fallback = kwargs.pop("_default", None)
    text = TRANSLATIONS.get(language, {}).get(key) or TRANSLATIONS[DEFAULT_LANGUAGE].get(key) or fallback or key
    if kwargs:
        return text.format(**kwargs)
    return text


def query_help_text(fields: str) -> str:
    return t("query.help", fields=fields)
