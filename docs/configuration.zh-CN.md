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
| `runtime` | 否 | 内置 | 全局运行时默认项，包含轮询、保留策略、投递策略、回放行为、静默告警和验证码提取。 |
| `channel` | 否 | 内置 | 每个通道的公共默认配置。 |
| `target` | 是 | - | 由规则引用的命名转发目标。 |
| `sms` | 否 | 内置 | 短信/iMessage 转发规则。 |
| `notify` | 否 | 内置 | macOS 通知记录转发规则。 |
| `ipn` | 否 | 内置 | iPhone 镜像通知转发规则。 |
| `alarm` | 否 | 内置 | 失败和静默告警规则。 |

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
  rules:
    - name_mark: alerts
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
channel.<channel> < channel.<channel>.kinds.<kind> < target.<name> < rule.destinations[]
```

`kinds.<kind>` 覆盖层是完整的 channel 配置覆盖，可用于 `alarm` 等来源特定默认值。

运行时字段单独按以下顺序解析：

```text
runtime.<field> < <kind>.runtime.<field>
```

每个 kind 的 `runtime` 都是局部覆盖，未填写的字段会回退到根级 `runtime`。

## 运行时

`runtime` 定义所有消息源共用的默认行为。每个 kind 都可以在 `<kind>.runtime` 下覆盖其中任意子集。

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

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `check_interval` | `1` | 轮询间隔，单位秒，最小值为 `1`。 |
| `retention` | `{mode: count, value: 5000}` | 历史记录保留策略。某个消息源需要不同保留周期时，可在对应 kind 下覆盖。 |
| `strategy` | `until_success` | kind 默认投递策略。规则级 `strategy` 仍然可以覆盖它。 |
| `history_mode` | `from_now` | 启动时的游标行为。`from_now` 从当前源末尾开始；`replay` 会在可用时恢复已保存的远端游标。 |
| `stale_alarm_seconds` | `0` | 静默看门狗。`0` 表示关闭；大于 `0` 时，某个消息源超过对应秒数没有新消息就会触发 `alarm`。 |
| `code_pattern` | 内置识别器 | 自定义验证码提取。未配置时使用内置识别器；配置了 `rules` 后会按顺序匹配，命中第一条即返回；`group` 可以是数字索引或命名分组；`fallback_to_builtin` 决定在规则都未命中时是否回退到内置识别器。正则 flags 请直接写在 `pattern` 里，例如 `(?i)`。 |

## 短信规则

`sms.rules` 处理来自 macOS Messages 数据库的入站消息。

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

短信中可用于过滤器和模板的字段：

| 字段 | 说明 |
| --- | --- |
| `sender` | 发送方号码或 handle。 |
| `receiver` | Messages 中的接收方/主叫 id。 |
| `title` | 存在时为消息 subject。 |
| `subtitle` | 短信/iMessage 中始终为空。 |
| `body` | 消息正文。 |
| `text` | 仅运行时派生，由 `title`、`subtitle` 和 `body` 拼接而成，可用于过滤器/模板，也用于验证码识别。 |
| `code` | 识别到的验证码，如果存在。 |
| `timestamp` | Unix 时间戳。 |
| `time_str` | 格式化后的本地时间字符串。 |
| `source` | 配置的来源标签。 |
| `msg` | 当前规范化消息的紧凑 JSON。 |

## 通知规则

`notify.rules` 处理来自 macOS 通知中心的记录。配置至少一条 notify 规则后才会启用。

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

通知字段包含所有通用模板字段，并额外包含：

| 字段 | 说明 |
| --- | --- |
| `sender` | App bundle id，例如 `com.apple.MobileSMS`。 |
| `receiver` | 可解析时为可读 App 名称，否则为 bundle id。 |
| `title` | 通知标题。 |
| `subtitle` | 通知副标题。 |
| `body` | 通知正文。 |
| `text` | 仅运行时派生，由 `title`、`subtitle` 和 `body` 拼接而成，也用于验证码识别。 |
| `rec_id` | 通知记录 id。 |
| `delivered_date` | 原始 macOS 投递时间戳，用作游标。 |

## iPhone 通知规则

`ipn.rules` 处理通过 iPhone 镜像同步到 macOS 的 iPhone 通知。配置至少一条 ipn 规则后才会启用。

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

iPhone 通知字段包含所有通用模板字段，并额外包含：

| 字段 | 说明 |
| --- | --- |
| `sender` | iPhone App bundle id，例如 `com.example.ios`。 |
| `receiver` | 当前与 `sender` 相同；后续可解析显示名时会用于展示名称。 |
| `title` | 通知标题。 |
| `subtitle` | 可用时为通知副标题或 footer。 |
| `body` | 通知正文。 |
| `text` | 仅运行时派生，由 `title`、`subtitle` 和 `body` 拼接而成，也用于验证码识别。 |
| `app_uuid` | 远端通知存储中的 UUID 目录名。 |
| `notification_id` | iPhone 通知标识。 |
| `ipn_cursor` | 由 `AppNotificationCreationDate` 转换得到的 Unix 微秒游标。 |
| `created_at` | 来自 `AppNotificationCreationDate` 的原始 Unix 时间戳。 |

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

规则级 `strategy` 会覆盖 kind 运行时中的 `strategy`。

## 模板

字符串值可以使用 `{{var}}` 占位符。模板会在配置加载时校验，因此未知变量会快速失败。

```yaml
payload:
  title: "{{trans}}"
  body: "{{text}}\n{{source}} - {{time_str}}"
```

可用变量：

| 变量 | 说明 |
| --- | --- |
| `{{sender}}`, `{{receiver}}` | 消息源相关的发送方和接收方字段。 |
| `{{text}}`, `{{code}}` | 运行时由 `title`/`subtitle`/`body` 拼接出的文本和识别到的验证码。 |
| `{{trans}}` | 由 sender/receiver 用 ` <- ` 拼接出的流转文本。 |
| `{{timestamp}}`, `{{time_str}}` | 时间字段。 |
| `{{source}}` | 配置的来源标签。 |
| `{{msg}}` | 当前消息的紧凑 JSON。 |
| `{{title}}`, `{{subtitle}}`, `{{body}}` | 消息源的标题、副标题和正文。 |
| `{{error}}`, `{{traceback}}` | 仅 alarm 使用的字段。 |

## 条件值

任何值都可以根据运行时上下文选择不同分支：

```yaml
payload:
  title:
    $default: "{{trans}}"
    $code: "Code {{code}}"
  body:
    $default: "{{text}}\n{{source}} - {{time_str}}"
    $code: "{{trans}}\n{{text}}\n{{source}} - {{time_str}}"
```

允许的条件 key：

| Key | 使用场景 |
| --- | --- |
| `$default` | 普通消息或兜底分支。 |
| `$code` | 识别到验证码时。 |

## 字段重写

`field_rewrite` 可以在渲染 payload 之前，先对模板上下文字段做正则替换。每个字段下的规则会按顺序执行。

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

说明：

- `field_rewrite` 会在 payload 模板渲染前执行。
- key 是模板上下文字段，例如 `title`、`subtitle`、`body`、`text`、`trans`。
- 当 `body` 这样的基础字段被改写后，`text` 这类派生字段会自动重新计算。
- 正则 flags 请直接写在 `pattern` 里，例如 `(?i)` / `(?m)` / `(?s)`。

## 告警

以下场景会发送告警：

- 匹配到的规则按其策略投递失败。
- 消息处理抛出异常。
- 某个消息源在 `runtime.stale_alarm_seconds` 指定秒数内没有新消息，且该值大于 `0`。

示例：

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

## 保留策略覆盖

先在根级 `runtime` 中设置共享保留策略，再按需为某个 kind 单独覆盖：

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

`mode` 可以是 `count` 或 `days`。

## 命令行参数

```bash
msgflow [-d] [-c] [-m [-n N]] [-k sms|notify|ipn|all]
```

| 参数 | 说明 |
| --- | --- |
| `-d`, `--debug` | 使用 debug 配置、DEBUG 日志和完整 traceback。 |
| `-c`, `--check` | 向配置的 destinations 发送测试消息。 |
| `-m`, `--mock` | 通过转发流水线重放 fixture 消息。 |
| `--fixture-file` | 单一消息类型的 JSON fixture 文件；与 `--kind sms`、`--kind notify` 或 `--kind ipn` 配合使用。 |
| `--fixture-dir` | fixture 目录；当 `--kind all` 时，其中应包含已启用类型的 fixture。 |
| `-n`, `--num` | 要重放的 mock 消息数量，默认 `2`。 |
| `-k`, `--kind` | check/mock 的目标类型：`sms`、`notify`、`ipn` 或 `all`，默认 `all`。 |

示例：

```bash
msgflow --check
msgflow --debug
msgflow --mock --kind sms --fixture-file tests/fixtures/sms/sms.json
msgflow --mock --kind all --fixture-dir tests/fixtures
```

## 完整示例

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

## 游标与历史行为

- `sms` 使用 `message.ROWID` 作为游标，因此 iPhone 延迟同步时，不会跳过较早时间但较晚到达的消息。
- `notify` 使用 `record.delivered_date`，因为通知记录 id 可能在行被删除后复用。
- `ipn` 使用由 `AppNotificationCreationDate` 转换得到的 Unix 微秒游标，并通过文件变更触发，另有周期性兜底扫描。
- `history_mode: from_now` 时，会从当前源末尾开始，并忽略已保存的远端游标。
- `history_mode: replay` 时，会在可用时从 `~/.config/msgflow/history/history.db` 恢复远端通道游标。
- 仅本地通道（`notification`、`floating`）重启后始终从当前源末尾开始，以避免重复本地提醒。
- 历史查询 DSL 搜索 `title`、`subtitle`、`body` 等已存储字段；运行时派生的 `text` 会用于展示重建，但不是历史查询字段。
