TRANS_TITLE = "{{trans}}: {{title}}"
CODE_TITLE = "🌀 验证码 {{code}}"
SUBT_BODY_SRC_TIME = "{{subtitle}}\n{{body}}\n{{source}} - {{time_str}}"
MD_SUBT_BODY_SRC_TIME = "{{subtitle}}  \n{{body}}  \n{{source}} - {{time_str}}"
TRANS_TEXT_SRC_TIME = "{{trans}}\n{{text}}\n{{source}} - {{time_str}}"
MD_TRANS_TEXT_SRC_TIME = "{{trans}}  \n{{text}}  \n{{source}} - {{time_str}}"
ALARM_TITLE = "{{source}}: {{error}}"
ALARM_BODY = "{{msg}}\n\n{{traceback}}"
MD_ALARM_BODY = "{{msg}}  \n  \n{{traceback}}"
ALARM_COPY = f"{ALARM_TITLE}\n\n{ALARM_BODY}"

CONFIG_DEFAULTS = {
    "source": "msgflow",
    "check_interval": 1,
    "app": {
        "retention": {
            "sms": {"mode": "count", "value": 5000},
            "notify": {"mode": "days", "value": 30},
            "ipn": {"mode": "days", "value": 30},
        },
    },
    "target": {},
    "sms": {"strategy": "until_success"},
    "notify": {"strategy": "until_success"},
    "ipn": {"strategy": "until_success"},
    "alarm": {"strategy": "until_success"},
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
                "title": {"$default": TRANS_TITLE, "$code": CODE_TITLE},
                "body": {"$default": SUBT_BODY_SRC_TIME, "$code": TRANS_TEXT_SRC_TIME},
                "copy": {"$default": TRANS_TEXT_SRC_TIME, "$code": "{{code}}"},
                "autoCopy": {"$default": 0, "$code": 1},
                "level": {"$default": "active", "$code": "timeSensitive"},
            },
            "kinds": {
                "alarm": {
                    "payload": {
                        "title": ALARM_TITLE,
                        "body": ALARM_BODY,
                        "copy": ALARM_COPY,
                        "level": "timeSensitive",
                    },
                },
            },
        },
        "pushgo": {
            "logmarker": "🌸",
            "method": "POST",
            "url": "https://gateway.pushgo.cn/message",
            "payload": {
                "title": {"$default": TRANS_TITLE, "$code": CODE_TITLE},
                "body": {"$default": MD_SUBT_BODY_SRC_TIME, "$code": MD_TRANS_TEXT_SRC_TIME},
            },
            "kinds": {
                "alarm": {
                    "payload": {
                        "title": ALARM_TITLE,
                        "body": MD_ALARM_BODY,
                    },
                },
            },
        },
        "tgbot": {
            "logmarker": "🤖",
            "method": "POST",
            "payload": {
                "text": {
                    "$default": TRANS_TEXT_SRC_TIME,
                    "$code": f"{CODE_TITLE}\n{TRANS_TEXT_SRC_TIME}",
                },
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
            "kinds": {
                "alarm": {
                    "payload": {
                        "text": ALARM_COPY,
                    },
                },
            },
        },
        "lark": {
            "logmarker": "📘",
            "method": "POST",
            "payload": {
                "$default": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"blue\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{time_str}}\",\"tag\":\"lark_md\"}}]}}",
                "$code": "{\"header\":{\"template\":\"green\",\"title\":{\"content\":\"🌀 验证码 {{code}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"column_set\",\"flex_mode\":\"none\",\"background_style\":\"grey\",\"horizontal_spacing\":\"default\",\"columns\":[{\"tag\":\"column\",\"width\":\"weighted\",\"weight\":1,\"elements\":[{\"tag\":\"markdown\",\"text_align\":\"center\",\"content\":\"{{code}}\\n\"}]}]},{\"tag\":\"div\",\"text\":{\"content\":\"{{receiver}} <- {{sender}}\\n{{text}}\\n{{source}} - {{time_str}}\",\"tag\":\"lark_md\"}}]}"
            },
            "success_json": {"code": 0},
            "kinds": {
                "alarm": {
                    "payload": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"red\",\"title\":{\"content\":\"{{source}}: {{error}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{msg}}\\n\\n{{traceback}}\",\"tag\":\"lark_md\"}}]}}",
                },
            },
        },
        "notification": {
            "logmarker": "🔔",
            "payload": {
                "title": {"$default": TRANS_TITLE, "$code": CODE_TITLE},
                "body": {"$default": SUBT_BODY_SRC_TIME, "$code": TRANS_TEXT_SRC_TIME},
                "copy": {"$default": TRANS_TEXT_SRC_TIME, "$code": "{{code}}"},
                "autoCopy": {"$default": 0, "$code": 1},
            },
            "kinds": {
                "alarm": {
                    "payload": {
                        "title": ALARM_TITLE,
                        "body": ALARM_BODY,
                    },
                },
            },
        },
        "floating": {
            "logmarker": "🔖",
            "payload": {
                "title": {"$default": TRANS_TITLE, "$code": CODE_TITLE},
                "body": {"$default": SUBT_BODY_SRC_TIME, "$code": TRANS_TEXT_SRC_TIME},
                "input": {"$default": "{{text}}", "$code": "{{code}}"},
            },
            "kinds": {
                "alarm": {
                    "payload": {
                        "title": ALARM_TITLE,
                        "body": ALARM_BODY,
                        "input": ALARM_COPY,
                    },
                },
            },
        },
    },
}


CONFIG_TEMPLATE = """# msgflow runtime config
# Active fields below are the minimal valid config and also show example config.
# Commented blocks are examples. Uncomment and edit them to override defaults.
# Defaults not shown here are still merged from the built-in config.
# Config Priority: channel.<channel> < channel.<channel>.kinds.<kind> < target.<name> < rule.destinations[]

source: msgflow        # default: msgflow
check_interval: 1     # default: 1 second

# app:                # default: retention.sms=count/5000, retention.notify=days/30, retention.ipn=days/30
#   retention:
#     sms:
#       mode: count      # count | days
#       value: 5000
#     notify:
#       mode: days       # count | days
#       value: 30
#     ipn:
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
#         $default: "{{trans}}"
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
#       text: "{{trans}}\\n{{text}}"
#       parse_mode: HTML

# target:             # configure credentials/URLs here
#   webhook_test:
#     channel: webhook      # webhook | bark | pushgo | tgbot | lark | notification | floating
#     url: https://example.com/webhook
#     headers:
#       Authorization: Bearer token
#     params: {}
#     payload:
#       title: "{{trans}}"
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

# ipn:
#   strategy: until_success   # default: until_success; options: all | until_success
#   rules:                 # default: []
#     - name_mark: important
#       filters:
#         - type: selector
#           match:
#             code: true
#       destinations:
#         - target: app_notification
#         - target: lark_debug_bot
#
# alarm:
#   strategy: until_success   # default: until_success; options: all | until_success
#   rules:                 # default: []
#     - name_mark: runtime_error
#       filters:
#         - type: selector
#           match:
#             error: true
#       destinations:
#         - target: pushgo_alarm
#         - target: tgbot_debug_bot

"""
