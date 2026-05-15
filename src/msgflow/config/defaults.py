CONFIG_DEFAULTS = {
    "source": "msgflow",
    "check_interval": 1,
    "app": {
        "retention": {
            "sms": {
                "mode": "count",
                "value": 5000,
            },
            "notify": {
                "mode": "days",
                "value": 30,
            },
        },
    },
    "target": {},
    "sms": {
        "strategy": "until_success",
    },
    "notify": {
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
                    "$code": "🌀 验证码 {{code}}",
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
            "notify": {
                "payload": {
                    "title": {
                        "$default": "{{receiver}}: {{title}}",
                    },
                    "body": {
                        "$default": "{{subtitle}}\n{{body}}\n{{source}} - {{time_str}}",
                        "$code": "{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                    },
                    "copy": {
                        "$default": "{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                    },
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
                    "$code": "🌀 验证码 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}  \n{{source}} - {{time_str}}",
                    "$code": "{{receiver}} <- {{sender}}  \n{{text}}  \n{{source}} - {{time_str}}",
                    "$alarm": "{{msg}}  \n  \n{{traceback}}"
                },
            },
            "notify": {
                "payload": {
                    "title": {
                        "$default": "{{receiver}}: {{title}}",
                    },
                    "body": {
                        "$default": "{{subtitle}}  \n{{body}}  \n{{source}} - {{time_str}}",
                        "$code": "{{receiver}}: {{text}}  \n{{source}} - {{time_str}}",
                    },
                },
            },
        },
        "tgbot": {
            "logmarker": "🤖",
            "method": "POST",
            "payload": {
                "text": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$code": "🌀 验证码 {{code}}\n{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}"
                },
                "parse_mode": "HTML",
                "link_preview_options": {
                    "is_disabled": True
                }
            },
            "notify": {
                "payload": {
                    "text": {
                        "$default": "{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                        "$code": "🌀 验证码 {{code}}\n{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                    },
                },
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
            },
            "notify": {
                "payload": {
                    "$default": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"blue\",\"title\":{\"content\":\"{{receiver}}: {{title}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{subtitle}}\\n{{body}}\\n{{source}} - {{time_str}}\",\"tag\":\"lark_md\"}}]}}",
                    "$code": "{\"header\":{\"template\":\"green\",\"title\":{\"content\":\"{{receiver}}: {{title}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"column_set\",\"flex_mode\":\"none\",\"background_style\":\"grey\",\"horizontal_spacing\":\"default\",\"columns\":[{\"tag\":\"column\",\"width\":\"weighted\",\"weight\":1,\"elements\":[{\"tag\":\"markdown\",\"text_align\":\"center\",\"content\":\"验证码\\n{{code}}\\n\"}]}]},{\"tag\":\"div\",\"text\":{\"content\":\"{{subtitle}}\\n{{body}}\\n{{source}} - {{time_str}}\",\"tag\":\"lark_md\"}}]}",
                },
            },
        },
        "notification": {
            "logmarker": "🔔",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 验证码 {{code}}",
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
            },
            "notify": {
                "payload": {
                    "title": {
                        "$default": "{{receiver}}: {{title}}",
                    },
                    "body": {
                        "$default": "{{subtitle}}\n{{body}}\n{{source}} - {{time_str}}",
                        "$code": "{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                    },
                    "copy": {
                        "$default": "{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                    },
                },
            },
        }
        ,
        "floating": {
            "logmarker": "🔖",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 验证码 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}\n{{source}} - {{time_str}}",
                    "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}",
                    "$alarm": "{{msg}}\n\n{{traceback}}",
                },
                "input": {
                    "$default": "{{text}}",
                    "$code": "{{code}}",
                    "$alarm": "{{msg}}",
                },
            },
            "notify": {
                "payload": {
                    "title": {
                        "$default": "{{receiver}}: {{title}}",
                    },
                    "body": {
                        "$default": "{{subtitle}}\n{{body}}\n{{source}} - {{time_str}}",
                        "$code": "{{receiver}}: {{text}}\n{{source}} - {{time_str}}",
                    },
                    "input": {
                        "$default": "{{text}}",
                        "$code": "{{code}}",
                    },
                },
            },
        },
    }
}


CONFIG_TEMPLATE = """# msgflow runtime config
# Active fields below are the minimal valid config and also show example config.
# Commented blocks are examples. Uncomment and edit them to override defaults.
# Defaults not shown here are still merged from the built-in config.
# Config Priority: channel.<channel> < target.<name> < rule.destinations[]

source: msgflow        # default: msgflow
check_interval: 1     # default: 1 second

# app:                # default: retention.sms=count/5000, retention.notify=days/30
#   retention:
#     sms:
#       mode: count      # count | days
#       value: 5000
#     notify:
#       mode: days       # count | days
#       value: 30

# channel:            # defaults are built in; uncomment fields to override
#   webhook:
#     logmarker: "🌐"      # default: 🌐
#     method: POST          # default: POST
#   bark:
#     method: POST          # default: POST
#     url: https://api.day.app/push  # default: https://api.day.app/push
#     payload:
#       title:
#         $default: "{{receiver}} <- {{sender}}"
#         $code: "🌀 验证码 {{code}}"
#       body:
#         $default: "{{text}}\\n{{source}} - {{time_str}}"
#   pushgo:
#     method: POST          # default: POST
#     url: https://gateway.pushgo.cn/message  # default: https://gateway.pushgo.cn/message
#   tgbot:
#     method: POST          # default: POST
#     payload:
#       chat_id: "123456"
#       text: "{{receiver}} <- {{sender}}\\n{{text}}"
#       parse_mode: HTML

# target:             # configure credentials/URLs here
#   webhook_test:
#     channel: webhook      # webhook | bark | pushgo | tgbot | lark | notification | floating
#     url: https://example.com/webhook
#     headers:
#       Authorization: Bearer token
#     params: {}
#     payload:
#       title: "{{receiver}} <- {{sender}}"
#       body: "{{text}}"
#     timeout: 10
#     success_json:
#       code: 0
#   bark_test_devices:
#     channel: bark
#     payload:
#       group: debug
#       device_keys:
#         - xxx
#         - xxx
#       icon: xxx
#   pushgo_alarm:
#     channel: pushgo
#     payload:
#       channel_id: xxx
#       password: xxx
#   tgbot_debug_bot:
#     channel: tgbot
#     url: https://api.telegram.org/bot<TOKEN>/sendMessage
#     payload:
#       chat_id: xxx
#   lark_debug_bot:
#     channel: lark
#     url: https://open.larkoffice.com/open-apis/bot/v2/hook/<TOKEN>
#   app_notification:
#     channel: notification
#   app_floating:
#     channel: floating

# sms:
#   strategy: until_success   # default: until_success; options: all | until_success
#   rules:                 # default: []
#     - name_mark: code
#       strategy: until_success
#       filters:
#         - type: selector
#           match:
#             code: true
#       destinations:
#         - target: webhook_test
#         - target: bark_test_devices
#         - target: app_floating

# notify:
#   strategy: until_success   # default: until_success; options: all | until_success
#   rules:                 # default: []
#     - name_mark: important
#       filters:
#         - type: and
#           match:
#             title: ".*"
#       destinations:
#         - target: app_notification
#         - target: lark_debug_bot

# alarm:
#   strategy: until_success   # default: until_success; options: all | until_success
#   destinations:          # default: []
#     - target: pushgo_alarm
#     - target: tgbot_debug_bot

"""
