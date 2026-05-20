# Configuration

This document is the user-facing reference for `~/.config/msgflow/config.yaml`.

## Config Path

MsgFlow reads:

```text
~/.config/msgflow/config.yaml
```

Debug mode reads:

```text
~/.config/msgflow/debug/config.yaml
```

The app stores history and logs under the same config root.

## Top-Level Fields

| Field | Required | Default | Description |
| --- | --- | --- | --- |
| `source` | No | `msgflow` | Device/source label exposed as `{{source}}`. |
| `runtime` | No | Built in | Global runtime defaults for polling, retention, strategy, replay behavior, stale alarms, and code detection. |
| `channel` | No | Built in | Shared defaults for each channel. |
| `target` | Yes | - | Named forwarding targets referenced by rules. |
| `sms` | No | Built in | SMS/iMessage forwarding rules. |
| `notify` | No | Built in | macOS notification forwarding rules. |
| `ipn` | No | Built in | iPhone mirrored notification forwarding rules. |
| `alarm` | No | Built in | Alarm rules for failure and silence alerts. |

Minimal config:

```yaml
source: My Mac

target:
  local_notify:
    channel: notification

sms:
  rules:
    - name_mark: all_sms
      destinations:
        - target: local_notify

alarm:
  rules:
    - name_mark: alerts
      destinations:
        - target: local_notify
```

## Channels

Supported channels:

| Channel | Type | Description |
| --- | --- | --- |
| `webhook` | HTTP | Generic HTTP request with configurable method, URL, params, headers, payload, timeout, and success JSON. |
| `bark` | HTTP | Bark push API. Defaults to `POST https://api.day.app/push`. |
| `pushgo` | HTTP | PushGo push API. Defaults to `POST https://gateway.pushgo.cn/message`. |
| `tgbot` | HTTP | Telegram Bot API. Escapes HTML text and wraps detected codes in `<code>`. |
| `lark` | HTTP | Lark bot webhook with card-message defaults and `success_json: {code: 0}`. |
| `notification` | Local | Native macOS notification through `msgflow-app`, with optional clipboard copy. |
| `floating` | Local | Floating panel near the cursor with fixed Type/Paste actions. |

HTTP channel fields:

| Field | Description |
| --- | --- |
| `method` | HTTP method, default `POST` for built-in HTTP channels. |
| `url` | Request URL; supports templates and conditional values. |
| `params` | Query parameters. |
| `headers` | Request headers. |
| `payload` | JSON request body. String payloads that contain JSON are parsed before rendering. |
| `timeout` | Request timeout as seconds or `(connect, read)`. |
| `success_json` | Optional structural subset match for response JSON. Without it, `status_code == 200` is success. |
| `logmarker` | Optional log prefix marker. |

Local `notification` payload:

| Field | Description |
| --- | --- |
| `title` | Notification title. |
| `body` | Notification body. |
| `copy` | Text copied when `autoCopy` is enabled. |
| `autoCopy` | Copies `copy` to clipboard when value is `1`. |

Local `floating` payload:

| Field | Description |
| --- | --- |
| `title` | Floating panel title. |
| `body` | Floating panel body. |
| `input` | Text used by the Type/Paste actions. |

## Targets

A target names a reusable destination.

```yaml
target:
  bark_phone:
    channel: bark
    payload:
      device_keys:
        - YOUR_BARK_KEY
      group: msgflow

  telegram_me:
    channel: tgbot
    url: https://api.telegram.org/bot<TOKEN>/sendMessage
    payload:
      chat_id: YOUR_CHAT_ID

  local_notify:
    channel: notification
```

Each rule references a target:

```yaml
destinations:
  - target: bark_phone
  - target: local_notify
```

The final destination config is merged in this order:

```text
channel.<channel> < channel.<channel>.kinds.<kind> < target.<name> < rule.destinations[]
```

The `kinds.<kind>` overlay is a complete channel-config override for source-specific defaults, such as `alarm`.

Runtime fields are resolved separately:

```text
runtime.<field> < <kind>.runtime.<field>
```

Each kind-level `runtime` block is a partial overlay. Missing fields fall back to root `runtime`.

## Runtime

`runtime` defines the shared defaults for every source kind. Each kind can override any subset under `<kind>.runtime`.

```yaml
runtime:
  check_interval: 1
  retention:
    mode: count
    value: 5000
  strategy: until_success
  history_mode: from_now
  stale_alarm_seconds: 0
  code_pattern:
    fallback_to_builtin: true
    rules:
      - pattern: "验证码[:：]\\s*(\\d{4,8})"
        group: 1
      - pattern: "(?i)code is (?P<c>\\d{6})"
        group: c
```

| Field | Default | Description |
| --- | --- | --- |
| `check_interval` | `1` | Poll interval in seconds, minimum `1`. |
| `retention` | `{mode: count, value: 5000}` | History retention policy. Override per kind when one source needs different retention. |
| `strategy` | `until_success` | Default delivery strategy for the kind. Rule-level `strategy` still overrides it. |
| `history_mode` | `from_now` | Startup cursor behavior. `from_now` starts at the current source tail; `replay` restores saved remote cursors when available. |
| `stale_alarm_seconds` | `0` | Silence watchdog. `0` disables it; values `> 0` trigger `alarm` when no new message arrives for that many seconds. |
| `code_pattern` | Built in detector | Custom verification-code extraction. If omitted, MsgFlow uses the built-in detector. When `rules` are configured, rules run in order and the first match wins; `group` can be an int or named group; `fallback_to_builtin` decides whether to try the built-in detector when no rule matches. Use inline regex flags like `(?i)` inside `pattern`. |

## SMS Rules

`sms.rules` handles inbound messages from the macOS Messages database.

```yaml
sms:
  runtime:
    strategy: until_success
    history_mode: replay
  rules:
    - name_mark: code_sms
      strategy: until_success
      filters:
        - type: selector
          match:
            code: true
        - type: or
          match:
            sender: "^10086$"
            receiver: "^\\+?8613"
      destinations:
        - target: local_notify
        - target: bark_phone
```

SMS fields available to filters and templates:

| Field | Description |
| --- | --- |
| `sender` | Sender phone number or handle. |
| `receiver` | Receiver/caller id from Messages. |
| `title` | Message subject when present. |
| `subtitle` | Always empty for SMS/iMessage. |
| `body` | Message body. |
| `text` | Runtime-only joined `title`, `subtitle`, and `body`, available to filters/templates and used for code detection. |
| `code` | Detected verification code, if any. |
| `timestamp` | Unix timestamp. |
| `time_str` | Formatted local time string. |
| `source` | Configured source label. |
| `msg` | Current normalized message as compact JSON. |

## Notification Rules

`notify.rules` handles records from macOS Notification Center. It is enabled when at least one notify rule is configured.

```yaml
notify:
  runtime:
    retention:
      mode: days
      value: 30
    strategy: all
  rules:
    - name_mark: important_apps
      filters:
        - type: or
          match:
            sender: "^com\\.apple\\.MobileSMS$"
            receiver: "^Telegram$"
      destinations:
        - target: local_notify
        - target: bark_phone
```

Notification fields include all common template fields plus:

| Field | Description |
| --- | --- |
| `sender` | App bundle id, such as `com.apple.MobileSMS`. |
| `receiver` | Human-readable app name when resolvable, otherwise bundle id. |
| `title` | Notification title. |
| `subtitle` | Notification subtitle. |
| `body` | Notification body. |
| `text` | Runtime-only joined `title`, `subtitle`, and `body`; also used for code detection. |
| `rec_id` | Notification record id. |
| `delivered_date` | Raw macOS delivery timestamp used as cursor. |

## iPhone Notification Rules

`ipn.rules` handles iPhone notifications mirrored to macOS by iPhone Mirroring. It is enabled when at least one ipn rule is configured.

```yaml
ipn:
  runtime:
    retention:
      mode: days
      value: 30
  rules:
    - name_mark: iphone_codes
      filters:
        - type: selector
          match:
            text: true
      destinations:
        - target: local_notify
        - target: bark_phone
```

iPhone notification fields include all common template fields plus:

| Field | Description |
| --- | --- |
| `sender` | iPhone app bundle id, such as `com.example.ios`. |
| `receiver` | Same as `sender` for now; reserved for a future display name when resolvable. |
| `title` | Notification title. |
| `subtitle` | Notification subtitle or footer when available. |
| `body` | Notification body. |
| `text` | Runtime-only joined `title`, `subtitle`, and `body`; also used for code detection. |
| `app_uuid` | UUID directory name under the remote notification store. |
| `notification_id` | iPhone notification identifier. |
| `ipn_cursor` | Unix microsecond cursor derived from `AppNotificationCreationDate`. |
| `created_at` | Raw Unix timestamp from `AppNotificationCreationDate`. |

## Filters

A rule matches only when every filter in `filters` passes.

| Type | Match Value | Behavior |
| --- | --- | --- |
| `and` | `{field: regex}` | Every regex must match from the start of the field value. |
| `or` | `{field: regex}` | At least one regex must match from the start of the field value. |
| `selector` | `{field: true/false}` | Checks whether the field has a truthy value. |

Examples:

```yaml
filters:
  - type: selector
    match:
      code: true
  - type: and
    match:
      sender: "^10086$"
```

```yaml
filters:
  - type: or
    match:
      receiver: "Telegram"
      text: ".*urgent"
```

## Delivery Strategies

| Strategy | Behavior |
| --- | --- |
| `until_success` | Try destinations in order and stop after the first success. If all fail, trigger `alarm`. |
| `all` | Try every destination. If any destination fails, trigger `alarm`. |

A rule-level `strategy` overrides the kind runtime `strategy`.

## Templates

String values can use `{{var}}` placeholders. Templates are validated at config load time, so unknown variables fail fast.

```yaml
payload:
  title: "{{trans}}"
  body: "{{text}}\n{{source}} - {{time_str}}"
```

Available variables:

| Variable | Description |
| --- | --- |
| `{{sender}}`, `{{receiver}}` | Source-specific sender and receiver fields. |
| `{{text}}`, `{{code}}` | Runtime-only joined `title`/`subtitle`/`body` text and detected verification code. |
| `{{trans}}` | Sender/receiver transition text joined as `sender <- receiver`. |
| `{{timestamp}}`, `{{time_str}}` | Time fields. |
| `{{source}}` | Configured source label. |
| `{{msg}}` | Current message as compact JSON. |
| `{{title}}`, `{{subtitle}}`, `{{body}}` | Source title, subtitle, and body fields. |
| `{{error}}`, `{{traceback}}` | Alarm-only fields. |

## Conditional Values

Any value can choose a different branch by runtime context:

```yaml
payload:
  title:
    $default: "{{trans}}"
    $code: "Code {{code}}"
  body:
    $default: "{{text}}\n{{source}} - {{time_str}}"
    $code: "{{trans}}\n{{text}}\n{{source}} - {{time_str}}"
```

Allowed conditional keys are:

| Key | Used When |
| --- | --- |
| `$default` | Normal messages or fallback. |
| `$code` | A verification code is detected. |

## Field Rewrite

`field_rewrite` lets a destination rewrite template-context fields with regex before payload rendering. Rules run in order per field.

```yaml
target:
  safe_webhook:
    channel: webhook
    url: https://example.com/webhook
    field_rewrite:
      body:
        - pattern: "(?i)https?://\\S+"
          replace: "[link]"
      text:
        - pattern: "(\\d{3})\\d{4}(\\d{4})"
          replace: "\\1****\\2"
    payload:
      title: "{{trans}}"
      body: "{{text}}"
```

Notes:

- `field_rewrite` is applied before payload templates are rendered.
- The keys are template-context fields such as `title`, `subtitle`, `body`, `text`, or `trans`.
- When a base field like `body` is rewritten, derived fields such as `text` are recomputed automatically.
- Use inline regex flags like `(?i)` / `(?m)` / `(?s)` inside `pattern`.

## Alarm

Alarms are sent when:

- A matched rule fails by its strategy.
- Message processing raises an exception.
- A source receives no new messages for `runtime.stale_alarm_seconds` seconds when that value is greater than `0`.

Example:

```yaml
alarm:
  runtime:
    strategy: until_success
  rules:
    - name_mark: alerts
      filters:
        - type: selector
          match:
            error: true
      destinations:
        - target: bark_phone
          payload:
            title: "{{source}}: {{error}}"
            body: "{{msg}}\n\n{{traceback}}"
```

## Retention Overrides

Set the shared retention policy in root `runtime`, then override it per kind when needed:

```yaml
runtime:
  retention:
    mode: count
    value: 5000

notify:
  runtime:
    retention:
      mode: days
      value: 30

ipn:
  runtime:
    retention:
      mode: days
      value: 30
```

`mode` can be `count` or `days`.

## Command-Line Options

```bash
msgflow [-d] [-c] [-m [-n N]] [-k sms|notify|ipn|all]
```

| Option | Description |
| --- | --- |
| `-d`, `--debug` | Use debug config, DEBUG logs, and full tracebacks. |
| `-c`, `--check` | Send a test message to configured destinations. |
| `-m`, `--mock` | Replay fixture messages through the forwarding pipeline. |
| `--fixture-file` | JSON fixture file for one kind; use with `--kind sms`, `--kind notify`, or `--kind ipn`. |
| `--fixture-dir` | Fixture directory; with `--kind all`, it should contain fixtures for enabled kinds. |
| `-n`, `--num` | Number of mock messages to replay. Default is `2`. |
| `-k`, `--kind` | Target kind for check/mock: `sms`, `notify`, `ipn`, or `all`. Default is `all`. |

Examples:

```bash
msgflow --check
msgflow --debug
msgflow --mock --kind sms --fixture-file tests/fixtures/sms/sms.json
msgflow --mock --kind all --fixture-dir tests/fixtures
```

## Complete Example

```yaml
source: MacBook

runtime:
  check_interval: 3
  retention:
    mode: count
    value: 5000
  strategy: until_success
  history_mode: from_now
  stale_alarm_seconds: 0

channel:
  bark:
    url: https://api.day.app/push
  tgbot:
    payload:
      parse_mode: HTML
      link_preview_options:
        is_disabled: true

target:
  bark_phone:
    channel: bark
    payload:
      device_keys:
        - YOUR_BARK_KEY
      group: msgflow

  telegram_me:
    channel: tgbot
    url: https://api.telegram.org/bot<TOKEN>/sendMessage
    payload:
      chat_id: YOUR_CHAT_ID

  local_notify:
    channel: notification
    payload:
      title: "{{receiver}} <- {{sender}}"
      body: "{{text}}\n{{source}} - {{time_str}}"
      copy: "{{text}}"
      autoCopy: 0

  code_panel:
    channel: floating
    field_rewrite:
      body:
        - pattern: "(\\d{3})\\d{2}(\\d{3})"
          replace: "\\1**\\2"
    payload:
      title:
        $default: "{{trans}}"
        $code: "Code {{code}}"
      body:
        $default: "{{text}}\n{{source}} - {{time_str}}"
        $code: "{{trans}}\n{{text}}\n{{source}} - {{time_str}}"
      input:
        $default: "{{text}}"
        $code: "{{code}}"

sms:
  runtime:
    history_mode: replay
    code_pattern:
      fallback_to_builtin: true
      rules:
        - pattern: "(?i)code[:：]\\s*(?P<c>\\d{6})"
          group: c
  rules:
    - name_mark: sms_codes
      filters:
        - type: selector
          match:
            code: true
      destinations:
        - target: code_panel
        - target: bark_phone
        - target: telegram_me

notify:
  runtime:
    strategy: all
    retention:
      mode: days
      value: 30
  rules:
    - name_mark: important_notifications
      filters:
        - type: or
          match:
            sender: "^com\\.apple\\.MobileSMS$"
            receiver: "^Telegram$"
      destinations:
        - target: local_notify
        - target: bark_phone

ipn:
  runtime:
    retention:
      mode: days
      value: 30
  rules:
    - name_mark: iphone_notifications
      filters:
        - type: selector
          match:
            text: true
      destinations:
        - target: local_notify
        - target: bark_phone

alarm:
  runtime:
    strategy: until_success
  rules:
    - name_mark: alerts
      filters:
        - type: selector
          match:
            error: true
      destinations:
        - target: bark_phone
          payload:
            title: "{{source}}: {{error}}"
            body: "{{msg}}\n\n{{traceback}}"
```

## Cursor and History Behavior

- `sms` uses `message.ROWID` as the cursor so delayed iPhone sync does not skip older timestamps that arrive later.
- `notify` uses `record.delivered_date` because notification record ids can be reused after rows are deleted.
- `ipn` uses a Unix microsecond cursor derived from `AppNotificationCreationDate` and is triggered by file changes with a periodic fallback scan.
- With `history_mode: from_now`, destinations start from the current source tail and ignore saved remote cursors.
- With `history_mode: replay`, remote channel cursors are restored from `~/.config/msgflow/history/history.db` when available.
- Local-only channels (`notification`, `floating`) always start from the current source tail on restart to avoid duplicate local alerts.
- History Query DSL searches stored fields such as `title`, `subtitle`, and `body`; runtime-only `text` is recomputed for display but is not a history query field.
