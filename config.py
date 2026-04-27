import os, yaml, copy
from typing import Optional
from base import deep_merge_dicts

cfg: Optional["Config"] = None

config_dir_default = '~/.config/msgflow'
config_dir_debug = f"{config_dir_default}/debug"
config_file = 'config.yaml'
record_file = 'record.json'

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
    def __init__(self, debug: bool = False):
        self.default_cfg = copy.deepcopy(CONFIG_DEFAULTS)
        self.debug_mode = debug
    
    def _update_cfg(self, config_dir):
        self.config_file_path = os.path.expanduser(f"{config_dir}/{config_file}")
        self.record_file_path = os.path.expanduser(f"{config_dir}/{record_file}")
        if not os.path.exists(self.config_file_path):
            raise FileNotFoundError(
                f"config file not found: {self.config_file_path}. "
                f"please create it (see README) or pass -d to use debug config at {os.path.expanduser(config_dir_debug)}/{config_file}"
            )
        with open(self.config_file_path, 'r') as fp:
            self.user_cfg = yaml.safe_load(fp) or {}
        self.effective_cfg = deep_merge_dicts(self.default_cfg, self.user_cfg)
        self.forward_rules = self._build_forward_rules()
        self.forward_destinations = self._flatten_forward_destinations()
        self.alarm_destinations = self._build_alarm_destinations()
        self.built_cfg = deep_merge_dicts(
            self.effective_cfg,
            {
                "forward": {"rules": self.forward_rules},
                "alarm": {"destinations": self.alarm_destinations},
            },
        )

    @property
    def debug_mode(self):
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, value):
        self._debug_mode = value
        if self._debug_mode:
            self._update_cfg(config_dir_debug)
        else:
            self._update_cfg(config_dir_default)
        

    def _resolve_destination(self, destination):
        target_name = destination.get('target') or ''
        user_target_cfg = (self.effective_cfg.get('target') or {}).get(target_name) or {}
        channel_name = user_target_cfg.get('channel') or destination.get('channel') or ''
        channel_cfg = (self.effective_cfg.get('channel') or {}).get(channel_name) or {}

        merged = deep_merge_dicts(channel_cfg, user_target_cfg)
        merged = deep_merge_dicts(merged, destination)
        merged['name_mark'] = destination.get('name_mark') or target_name
        return merged

    def _build_destinations(self, destinations, name_mark_prefix: str = ""):
        built = []
        name_marks = set()
        for dest in destinations:
            dest_merged = self._resolve_destination(dest)
            name_mark = dest_merged['name_mark']
            if name_mark_prefix:
                name_mark = f"{name_mark_prefix}_{name_mark}"
                dest_merged["name_mark"] = name_mark
            if name_mark in name_marks:
                raise Exception(f"duplicate destination name_mark '{name_mark}'")
            name_marks.add(name_mark)
            built.append(dest_merged)
        return built

    def _build_forward_rules(self):
        fwd_opt = self.effective_cfg.get("forward")
        fwd_strategy = fwd_opt.get("strategy")
        rules = fwd_opt.get('rules') or []
        built_rules = []
        for idx, rule in enumerate(rules):
            rule_name_mark = rule.get("name_mark") or f"rule_{idx}"
            filters = rule.get("filters") or []
            strategy = rule.get("strategy") or fwd_strategy
            destinations = rule.get("destinations") or []
            try:
                built_dests = self._build_destinations(destinations, name_mark_prefix=rule_name_mark)
            except Exception as e:
                raise Exception(f"build_forward_rules error: rule[{idx}] '{rule_name_mark}' destinations: {e}")

            built_rules.append(
                {
                    "name_mark": rule_name_mark,
                    "filters": filters,
                    "strategy": strategy,
                    "destinations": built_dests,
                }
            )
        return built_rules

    def _flatten_forward_destinations(self):
        flat = []
        for rule in self.forward_rules:
            flat.extend(rule.get("destinations") or [])
        return flat

    def _build_alarm_destinations(self):
        alarm_opt = self.effective_cfg.get("alarm") or {}
        destinations = alarm_opt.get('destinations') or []
        try:
            return self._build_destinations(destinations)
        except Exception as e:
            raise Exception(f"build_alarm_destinations error: {e}")


def getcfg() -> "Config":
    global cfg
    if cfg is None:
        cfg = Config()
    return cfg
