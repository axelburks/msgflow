import os
import yaml

config_dir = '~/.config/msgflow'
config_dir_debug = f"{config_dir}/debug"
config_file = 'config.yaml'
record_file = 'record.json'

CONFIG_DEFAULTS = {
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
                    "$default": "{{text}}\n{{source}} - {{receive_time}}",
                    "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                    "$alarm": "{{msg}}\n\n{{traceback}}"
                },
                "copy": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
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
                    "$default": "{{text}}  \n{{source}} - {{receive_time}}",
                    "$code": "{{receiver}} <- {{sender}}  \n{{text}}  \n{{source}} - {{receive_time}}",
                    "$alarm": "{{msg}}  \n  \n{{traceback}}"
                },
            }
        },
        "tgbot": {
            "logmarker": "🤖",
            "method": "POST",
            "payload": {
                "text": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                    "$code": "🌀 {{code}}\n{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
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
                "$default": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"blue\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{receive_time}}\",\"tag\":\"lark_md\"}}]}}",
                "$code": "{\"header\":{\"template\":\"green\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"column_set\",\"flex_mode\":\"none\",\"background_style\":\"grey\",\"horizontal_spacing\":\"default\",\"columns\":[{\"tag\":\"column\",\"width\":\"weighted\",\"weight\":1,\"elements\":[{\"tag\":\"markdown\",\"text_align\":\"center\",\"content\":\"验证码\\n{{code}}\\n\"}]}]},{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{receive_time}}\",\"tag\":\"lark_md\"}}]}",
                "$alarm": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"red\",\"title\":{\"content\":\"{{source}}: {{error}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{msg}}\\n\\n{{traceback}}\",\"tag\":\"lark_md\"}}]}}"
            },
            "success_json": {
                "code": 0,
            }
        },
        "notification": {
            "logmarker": "🔔",
            "title": {
                "$default": "{{receiver}} <- {{sender}}",
                "$code": "🌀 {{code}}",
                "$alarm": "{{source}}: {{error}}",
            },
            "body": {
                "$default": "{{text}}\n{{source}} - {{receive_time}}",
                "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                "$alarm": "{{msg}}\n\n{{traceback}}"
            },
            "copy": {
                "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
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


class Config:
    def __init__(self):
        self._debug_mode = False
        self._update_config()

    def _update_config(self):
        self._config_file_path = os.path.expanduser(f"{config_dir}/{config_file}")
        self._record_file_path = os.path.expanduser(f"{config_dir}/{record_file}")
        with open(self._config_file_path, 'r') as fp:
            self._user_config = yaml.safe_load(fp)

    @property
    def debug_mode(self):
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, value):
        self._debug_mode = value
        if self._debug_mode:
            global config_dir
            config_dir = config_dir_debug
        self._update_config()

    @property
    def record_file_path(self):
        return self._record_file_path

    @property
    def user_config(self):
        return self._user_config


config = Config()