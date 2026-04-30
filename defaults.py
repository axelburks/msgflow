CONFIG_DEFAULTS = {
    "check_interval": 3,
    "source": "msgflow",
    "forward": {
        "strategy": "until_success",
    },
    "alarm": {
        "strategy": "until_success",
    },
    "channel": {
        "webhook": {
            "logmarker": "🌐",
            "method": "POST",
        },
        "bark": {
            "logmarker": "📣",
            "method": "POST",
            "url": "https://api.day.app/push",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}\n{{source}} - {{time_str}}",
                    "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$alarm": "{{msg}}\n\n{{traceback}}"
                },
                "copy": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$code": "{{code}}",
                    "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}"
                },
                "autoCopy": {
                    "$default": 0,
                    "$code": 1,
                    "$alarm": 0
                },
                "level": {
                    "$default": "active",
                    "$code": "timeSensitive",
                    "$alarm": "timeSensitive"
                },
            },
        },
        "pushgo": {
            "logmarker": "🌸",
            "method": "POST",
            "url": "https://gateway.pushgo.cn/message",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}  \n{{source}} - {{time_str}}",
                    "$code": "{{receiver}} <- {{sender}}  \n{{text}}  \n{{source}} - {{time_str}}",
                    "$alarm": "{{msg}}  \n  \n{{traceback}}"
                },
            }
        },
        "tgbot": {
            "logmarker": "🤖",
            "method": "POST",
            "payload": {
                "text": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$code": "🌀 {{code}}\n{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}"
                },
                "parse_mode": "HTML",
                "link_preview_options": {
                    "is_disabled": True
                }
            },
        },
        "lark": {
            "logmarker": "📘",
            "method": "POST",
            "payload": {
                "$default": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"blue\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{time_str}}\",\"tag\":\"lark_md\"}}]}}",
                "$code": "{\"header\":{\"template\":\"green\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"column_set\",\"flex_mode\":\"none\",\"background_style\":\"grey\",\"horizontal_spacing\":\"default\",\"columns\":[{\"tag\":\"column\",\"width\":\"weighted\",\"weight\":1,\"elements\":[{\"tag\":\"markdown\",\"text_align\":\"center\",\"content\":\"验证码\\n{{code}}\\n\"}]}]},{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{time_str}}\",\"tag\":\"lark_md\"}}]}",
                "$alarm": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"red\",\"title\":{\"content\":\"{{source}}: {{error}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{msg}}\\n\\n{{traceback}}\",\"tag\":\"lark_md\"}}]}}"
            },
            "success_json": {
                "code": 0,
            }
        },
        "notification": {
            "logmarker": "🔔",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}\n{{source}} - {{time_str}}",
                    "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$alarm": "{{msg}}\n\n{{traceback}}"
                },
                "copy": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$code": "{{code}}",
                    "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}",
                },
                "autoCopy": {
                    "$default": 0,
                    "$code": 1,
                    "$alarm": 0
                }
            }
        }
    }
}
