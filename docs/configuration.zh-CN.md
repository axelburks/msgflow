# 配置文档

本文档是 `~/.config/msgflow/config.yaml` 的用户配置参考。

## 配置路径

MsgFlow 读取：

```text
~/.config/msgflow/config.yaml
```

Debug 模式读取：

```text
~/.config/msgflow/debug/config.yaml
```

App 会在同一个配置根目录下保存历史记录和日志。

## 顶层字段

| 字段 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `source` | 否 | `msgflow` | 暴露为 `{{source}}` 的设备/来源标签。 |
| `check_interval` | 否 | `1` | 轮询间隔，单位为秒，最小值为 `1`。 |
| `channel` | 否 | 内置 | 每个通道的公共默认配置。 |
| `target` | 是 | - | 由规则引用的命名转发目标。 |
| `sms` | 否 | 内置 | 短信/iMessage 转发规则。 |
| `notify` | 否 | 内置 | macOS 通知记录转发规则。 |
| `alarm` | 否 | 内置 | 失败和静默告警的投递目标。 |
| `app` | 否 | 内置 | App 历史记录保留设置。 |

最小配置：

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
  destinations:
    - target: local_notify
```

## 通道

支持的通道：

| 通道 | 类型 | 说明 |
| --- | --- | --- |
| `webhook` | HTTP | 通用 HTTP 请求，支持配置 method、URL、params、headers、payload、timeout 和 success JSON。 |
| `bark` | HTTP | Bark 推送 API，默认 `POST https://api.day.app/push`。 |
| `pushgo` | HTTP | PushGo 推送 API，默认 `POST https://gateway.pushgo.cn/message`。 |
| `tgbot` | HTTP | Telegram Bot API，会转义 HTML 文本，并用 `<code>` 包裹识别到的验证码。 |
| `lark` | HTTP | 飞书机器人 webhook，默认使用卡片消息，并设置 `success_json: {code: 0}`。 |
| `notification` | 本地 | 通过 `msgflow-app` 发送 macOS 原生通知，可选复制到剪贴板。 |
| `floating` | 本地 | 在光标附近显示浮窗，提供固定的 Type/Paste 操作。 |

HTTP 通道字段：

| 字段 | 说明 |
| --- | --- |
| `method` | HTTP 方法，内置 HTTP 通道默认使用 `POST`。 |
| `url` | 请求 URL，支持模板和条件值。 |
| `params` | 查询参数。 |
| `headers` | 请求头。 |
| `payload` | JSON 请求体。包含 JSON 的字符串 payload 会先解析再渲染。 |
| `timeout` | 请求超时时间，可为秒数或 `(connect, read)`。 |
| `success_json` | 可选的响应 JSON 结构子集匹配。不配置时，`status_code == 200` 即为成功。 |
| `logmarker` | 可选日志前缀标记。 |

本地 `notification` payload：

| 字段 | 说明 |
| --- | --- |
| `title` | 通知标题。 |
| `body` | 通知正文。 |
| `copy` | 启用 `autoCopy` 时复制的文本。 |
| `autoCopy` | 值为 `1` 时将 `copy` 复制到剪贴板。 |

本地 `floating` payload：

| 字段 | 说明 |
| --- | --- |
| `title` | 浮窗标题。 |
| `body` | 浮窗正文。 |
| `input` | Type/Paste 操作使用的文本。 |

## 目标

target 定义可复用的投递目标。

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

每条规则引用一个 target：

```yaml
destinations:
  - target: bark_phone
  - target: local_notify
```

最终 destination 配置按以下顺序合并：

```text
channel.<channel> < channel.<channel>.<kind> < target.<name> < rule.destinations[]
```

`<kind>` 覆盖层可以是 `sms` 或 `notify`，用于让同一通道针对不同消息源使用不同默认值。

## 短信规则

`sms.rules` 处理来自 macOS Messages 数据库的入站消息。

```yaml
sms:
  strategy: until_success
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

短信中可用于过滤器和模板的字段：

| 字段 | 说明 |
| --- | --- |
| `sender` | 发送方号码或 handle。 |
| `receiver` | Messages 中的接收方/主叫 id。 |
| `text` | 消息文本。 |
| `code` | 识别到的验证码，如果存在。 |
| `timestamp` | Unix 时间戳。 |
| `time_str` | 格式化后的本地时间字符串。 |
| `source` | 配置的来源标签。 |
| `msg` | 当前规范化消息的紧凑 JSON。 |

## 通知规则

`notify.rules` 处理来自 macOS 通知中心的记录。配置至少一条 notify 规则后才会启用。

```yaml
notify:
  strategy: until_success
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

通知字段包含所有通用模板字段，并额外包含：

| 字段 | 说明 |
| --- | --- |
| `sender` | App bundle id，例如 `com.apple.MobileSMS`。 |
| `receiver` | 可解析时为可读 App 名称，否则为 bundle id。 |
| `title` | 通知标题。 |
| `subtitle` | 通知副标题。 |
| `body` | 通知正文。 |
| `text` | 由 `title`、`subtitle` 和 `body` 拼接而成，也用于验证码识别。 |
| `rec_id` | 通知记录 id。 |
| `delivered_date` | 原始 macOS 投递时间戳，用作游标。 |

## 过滤器

只有当 `filters` 中的每个过滤器都通过时，规则才会匹配。

| 类型 | 匹配值 | 行为 |
| --- | --- | --- |
| `and` | `{field: regex}` | 每个正则都必须从字段值开头开始匹配。 |
| `or` | `{field: regex}` | 至少一个正则必须从字段值开头开始匹配。 |
| `selector` | `{field: true/false}` | 检查字段是否为真值。 |

示例：

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

## 投递策略

| 策略 | 行为 |
| --- | --- |
| `until_success` | 按顺序尝试 destinations，并在第一次成功后停止。如果全部失败，则触发 `alarm`。 |
| `all` | 尝试每个 destination。如果任一 destination 失败，则触发 `alarm`。 |

规则级 `strategy` 会覆盖消息源级 `strategy`。

## 模板

字符串值可以使用 `{{var}}` 占位符。模板会在配置加载时校验，因此未知变量会快速失败。

```yaml
payload:
  title: "{{receiver}} <- {{sender}}"
  body: "{{text}}\n{{source}} - {{time_str}}"
```

可用变量：

| 变量 | 说明 |
| --- | --- |
| `{{sender}}`, `{{receiver}}` | 消息源相关的发送方和接收方字段。 |
| `{{text}}`, `{{code}}` | 消息文本和识别到的验证码。 |
| `{{timestamp}}`, `{{time_str}}` | 时间字段。 |
| `{{source}}` | 配置的来源标签。 |
| `{{msg}}` | 当前消息的紧凑 JSON。 |
| `{{title}}`, `{{subtitle}}`, `{{body}}` | 通知字段。 |
| `{{error}}`, `{{traceback}}` | 仅 alarm 使用的字段。 |

## 条件值

任何值都可以根据运行时上下文选择不同分支：

```yaml
payload:
  title:
    $default: "{{receiver}} <- {{sender}}"
    $code: "Code {{code}}"
    $alarm: "{{source}}: {{error}}"
  body:
    $default: "{{text}}\n{{source}} - {{time_str}}"
    $code: "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}"
    $alarm: "{{msg}}\n\n{{traceback}}"
```

允许的条件 key：

| Key | 使用场景 |
| --- | --- |
| `$default` | 普通消息或兜底分支。 |
| `$code` | 识别到验证码时。 |
| `$alarm` | destination 为 alarm 渲染时。 |

## 告警

以下场景会发送告警：

- 匹配到的规则按其策略投递失败。
- 消息处理抛出异常。
- 某个消息源 24 小时没有收到新消息。

示例：

```yaml
alarm:
  strategy: until_success
  destinations:
    - target: bark_phone
      payload:
        title: "{{source}}: {{error}}"
        body: "{{msg}}\n\n{{traceback}}"
```

## App 保留策略

可以按消息类型配置历史记录保留策略：

```yaml
app:
  retention:
    sms:
      mode: count
      value: 5000
    notify:
      mode: days
      value: 30
```

`mode` 可以是 `count` 或 `days`。

## 命令行参数

```bash
msgflow [-d] [-c] [-m [-n N]] [-k sms|notify|all]
```

| 参数 | 说明 |
| --- | --- |
| `-d`, `--debug` | 使用 debug 配置、DEBUG 日志和完整 traceback。 |
| `-c`, `--check` | 向配置的 destinations 发送测试消息。 |
| `-m`, `--mock` | 通过转发流水线重放 fixture 消息。 |
| `--fixture-file` | 单一消息类型的 JSON fixture 文件；与 `--kind sms` 或 `--kind notify` 配合使用。 |
| `--fixture-dir` | fixture 目录；当 `--kind all` 时，其中应包含 `sms/sms.json` 和 `notify/notify.json`。 |
| `-n`, `--num` | 要重放的 mock 消息数量，默认 `2`。 |
| `-k`, `--kind` | check/mock 的目标类型：`sms`、`notify` 或 `all`，默认 `all`。 |

示例：

```bash
msgflow --check
msgflow --debug
msgflow --mock --kind sms --fixture-file tests/fixtures/sms/sms.json
msgflow --mock --kind all --fixture-dir tests/fixtures
```

## 完整示例

```yaml
check_interval: 3
source: MacBook

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
    payload:
      title:
        $default: "{{receiver}} <- {{sender}}"
        $code: "Code {{code}}"
      body:
        $default: "{{text}}\n{{source}} - {{time_str}}"
        $code: "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}"
      input:
        $default: "{{text}}"
        $code: "{{code}}"

sms:
  strategy: until_success
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
  strategy: all
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

alarm:
  strategy: until_success
  destinations:
    - target: bark_phone
      payload:
        title: "{{source}}: {{error}}"
        body: "{{msg}}\n\n{{traceback}}"
```

## 游标与历史行为

- `sms` 使用 `message.ROWID` 作为游标，因此 iPhone 延迟同步时，不会跳过较早时间但较晚到达的消息。
- `notify` 使用 `record.delivered_date`，因为通知记录 id 可能在行被删除后复用。
- 新 destinations 会从当前数据库末尾开始，不会自动回放历史消息。
- 远端通道游标会持久化到 `~/.config/msgflow/history/history.db`。
- 仅本地通道（`notification`、`floating`）会在重启时从当前数据库末尾开始，以避免重复本地提醒。
