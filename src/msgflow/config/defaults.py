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
    "runtime": {
        "check_interval": 1,
        "strategy": "until_success",
        "history_mode": "from_now",
        "stale_alarm_seconds": 0,
        "retention": {"mode": "count", "value": 5000},
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
                "$default": {
                    "msg_type": "interactive",
                    "card": {
                        "schema": "2.0",
                        "header": {
                            "template": "blue",
                            "title": {
                                "content": TRANS_TITLE,
                                "tag": "plain_text"
                            }
                        },
                        "body": {
                            "elements": [
                                {
                                    "tag": "div",
                                    "text": {
                                        "content": SUBT_BODY_SRC_TIME,
                                        "tag": "lark_md"
                                    }
                                }
                            ]
                        }
                    }
                },
                "$code": {
                    "msg_type": "interactive",
                    "card": {
                        "schema": "2.0",
                        "header": {
                            "template": "green",
                            "title": {
                                "content": CODE_TITLE,
                                "tag": "plain_text"
                            },
                            "subtitle": {
                                "content": TRANS_TITLE,
                                "tag": "plain_text"
                            }
                        },
                        "body": {
                            "elements": [
                                {
                                    "tag": "column_set",
                                    "flex_mode": "none",
                                    "background_style": "grey",
                                    "horizontal_spacing": "default",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "weight": 1,
                                            "elements": [
                                                {
                                                    "tag": "markdown",
                                                    "text_align": "center",
                                                    "content": "{{code}}"
                                                }
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "content": SUBT_BODY_SRC_TIME,
                                        "tag": "lark_md"
                                    }
                                }
                            ]
                        }
                    }
                }
            },
            "success_json": {"code": 0},
            "kinds": {
                "alarm": {
                    "payload": {
                        "msg_type": "interactive",
                        "card": {
                            "schema": "2.0",
                            "header": {
                                "template": "red",
                                "title": {
                                    "content": ALARM_TITLE,
                                    "tag": "plain_text"
                                }
                            },
                            "body": {
                                "elements": [
                                    {
                                        "tag": "div",
                                        "text": {
                                            "content": ALARM_BODY,
                                            "tag": "lark_md"
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
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
# Resolution priority for destinations:
#   channel.<channel> < channel.<channel>.kinds.<kind> < target.<name> < rule.destinations[]
# Resolution priority for runtime fields:
#   runtime.<field> < <kind>.runtime.<field>

source: msgflow        # default: msgflow

# runtime:                                # default: see below
#   check_interval: 1                     # default: 1 (seconds between polling ticks)
#   retention:                            # default: {mode: count, value: 5000}
#     mode: count                         # count | days
#     value: 5000
#   strategy: until_success               # default: until_success; options: all | until_success
#   history_mode: from_now                # default: from_now; options: from_now | replay
#   stale_alarm_seconds: 0                # default: 0 (disabled); >0 = alarm when no new msg for N seconds
#   code_pattern:                         # default: no rules, no fallback
#     fallback_to_builtin: false          # if user rules miss, fall back to built-in detector
#     rules:
#       - pattern: "验证码[:：]\\s*(\\d{4,8})"
#         group: 1                        # int index or named group; omit = whole match
#       - pattern: "(?i)code is (?P<c>\\d{6})"
#         group: c                        # inline flags like (?i)/(?m)/(?s) live in the pattern

# channel:            # defaults are built in; uncomment fields to override
#   bark:
#     method: POST          # default: POST
#     url: https://api.day.app/push  # default: https://api.day.app/push
#     payload:
#       title:
#         $default: "{{trans}}"
#         $code: "🌀 验证码 {{code}}"
#       body:
#         $default: "{{text}}\\n{{source}} - {{time_str}}"
#     field_rewrite:                      # regex rewrite over template-context fields
#       text:                              # key MUST be one of the template variables
#         - pattern: "(\\d{4})\\d{8}(\\d{4})"
#           replace: "\\1****\\2"
#       body:
#         - pattern: "(?i)https?://\\S+"   # use inline (?i)/(?m)/(?s) for flags
#           replace: "[link]"
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
#   runtime:                  # optional per-kind overlay; falls back to runtime.<field>
#     history_mode: replay
#     stale_alarm_seconds: 600
#   rules:
#     - name_mark: code
#       strategy: until_success    # optional rule-level override
#       filters:
#         - type: selector
#           match:
#             code: true
#       destinations:
#         - target: bark_test_devices
#         - target: app_floating

# notify:
#   runtime:
#     retention:
#       mode: days
#       value: 30
#   rules:
#     - name_mark: important
#       filters:
#         - type: and
#           match:
#             title: ".*"
#       destinations:
#         - target: app_notification
#         - target: lark_debug_bot

# ipn:
#   rules:
#     - name_mark: important
#       filters:
#         - type: selector
#           match:
#             code: true
#       destinations:
#         - target: app_notification

# alarm:
#   runtime:
#     strategy: until_success
#   rules:
#     - name_mark: runtime_error
#       filters:
#         - type: selector
#           match:
#             error: true
#       destinations:
#         - target: pushgo_alarm
#         - target: tgbot_debug_bot

"""
