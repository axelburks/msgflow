# MsgFlow — macOS 消息转发工具

在 macOS 上实时读取短信/通知等消息，按规则转发到 Bark / Telegram / 飞书 / PushGo / Webhook / 通知消息 等通道，并支持模板渲染。

---

## 目录

- [MsgFlow — macOS 消息转发工具](#msgflow--macos-消息转发工具)
  - [目录](#目录)
  - [特性](#特性)
  - [依赖环境](#依赖环境)
  - [快速开始](#快速开始)
  - [配置说明](#配置说明)
    - [顶层结构](#顶层结构)
    - [channel 通道公共配置](#channel-通道公共配置)
    - [target 转发目标](#target-转发目标)
    - [forward 转发规则](#forward-转发规则)
    - [alarm 异常告警](#alarm-异常告警)
  - [模板系统](#模板系统)
    - [值条件字典](#值条件字典)
    - [可用模板变量](#可用模板变量)
  - [配置合并与优先级](#配置合并与优先级)
  - [命令行参数](#命令行参数)
  - [完整示例](#完整示例)
  - [Roadmap](#roadmap)
  - [Credits](#credits)
  - [License](#license)

---

## 特性

- 实时监听 macOS 数据库，并可自动识别短信/通知等消息中的中文(简/繁)、英文验证码消息
- 多通道推送：`bark`、`tgbot`、`pushgo`、`lark`、`webhook`、`notification`（macOS 本地通知）
- 规则化转发：按 `filters`（and/or/selector 正则匹配）路由到不同 `destinations`
- 支持 `until_success` / `all` 两种投递策略
- 异常告警通道（alarm），失败自动上报
- 基于「值条件字典」的模板系统，可针对「默认 / 含验证码 / 告警」三种场景分别渲染标题、正文、复制内容
- 启动时通过 pydantic 对配置进行严格校验

## 依赖环境

- macOS（读取 `~/Library/Messages/chat.db`）
- Python 3.10+（代码使用了 `TypeAlias` 等类型特性）
- 已在 macOS 上开启「信息」并与 iPhone 使用同一 iCloud 账号、开启云端信息或短信转发
- 终端或 App 需被授予「完全磁盘访问权限」以读取短信数据库

## 快速开始

1. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```

2. 创建配置文件 `~/.config/msgflow/config.yaml`（最小可用示例）
   ```yaml
   target:
     local_notify:
       channel: notification

   forward:
     rules:
       - name_mark: default_rule
         destinations:
           - target: local_notify
   ```

3. 启动
   ```bash
   python msgflow.py
   ```

常用辅助命令：
```bash
python msgflow.py -c          # check：对所有转发目标发送一次测试消息，验证配置可用
python msgflow.py -m -n 3     # mock：从 sms/sms.json 中随机取 N 条模拟触发
python msgflow.py -d          # debug：加载 ~/.config/msgflow/debug/config.yaml，日志级别 DEBUG 
```

---

## 配置说明

配置文件默认路径：`~/.config/msgflow/config.yaml`（debug 模式下为 `~/.config/msgflow/debug/config.yaml`）。

### 顶层结构

| 字段 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `check_interval` | 否 | `3` | 检查新短信的间隔（秒），最小 `1` |
| `source` | 是 | — | 对应模板变量 `{{source}}`，用于标识来源设备 |
| `channel` | 否 | 见 [defaults.py](./defaults.py) | 各通道的公共默认配置 |
| `target` | 是 | — | 具体的转发目标定义，被 `forward` / `alarm` 引用 |
| `forward` | 是 | — | 短信转发规则 |
| `alarm` | 是 | — | 异常告警目标 |

### channel 通道公共配置

`channel.<name>` 为对应 `channel` 类型的公共默认值。所有内置通道均已在 [defaults.py](./defaults.py) 预置合理默认，用户通常无需全部覆盖。

支持的 `channel` 类型（见 [base.py](./base.py)）：

| channel | 类型 | 说明 |
| --- | --- | --- |
| `webhook` | 请求型 | 通用 HTTP 请求，透传 `method` / `url` / `params` / `headers` / `payload` |
| `bark` | 请求型 | [Bark](https://github.com/Finb/Bark) 推送，默认 `POST https://api.day.app/push` |
| `pushgo` | 请求型 | [PushGo](https://github.com/AldenClark/pushgo) 推送，默认 `POST https://gateway.pushgo.cn/message` |
| `tgbot` | 请求型 | Telegram Bot，自动对 HTML 文本转义并将 `{{code}}` 包裹为 `<code>` |
| `lark` | 请求型 | 飞书机器人，默认 payload 为卡片消息字符串模板 |
| `notification` | 本地 | 调用 `osascript` 弹出 macOS 通知；`autoCopy=1` 时自动把 `copy` 的内容写入剪贴板 |

请求型通道（`REQ_CHANNELS`）通用字段：

| 字段 | 说明 |
| --- | --- |
| `method` | HTTP 方法，默认 `POST` |
| `url` | 请求地址（支持模板、值条件字典） |
| `params` | Query 参数（dict）, 各字段支持模板、值条件字典 |
| `headers` | 请求头（dict）, 各字段支持模板、值条件字典 |
| `payload` | 请求体，作为 JSON 发送；字符串值会尝试解析为 JSON 后递归渲染；各字段支持模板、值条件字典 |
| `timeout` | 超时秒数或 `(connect, read)` |
| `success_json` | 成功判定的 JSON 子集匹配，如 `{code: 0}`；未配置时仅按 `status_code == 200` 判定 |
| `logmarker` | 日志前缀 emoji，便于观察 |

本地通道（`notification`）payload 字段：

| 字段 | 说明 |
| --- | --- |
| `title` | 通知标题（必填，支持模板、值条件字典） |
| `body` | 通知正文（必填，支持模板、值条件字典） |
| `copy` | 配合 `autoCopy` 复制到剪贴板的内容，支持模板、值条件字典 |
| `autoCopy` | `1` 时将 `copy` 内容写入剪贴板 |

### target 转发目标

```yaml
target:
  <target_name>:
    channel: bark            # 必填，取值见上表
    logmarker: "🎯"           # 可选
    # 其余字段会与 channel.<channel> 合并，最终被 destination 再次合并
```

### forward 转发规则

```yaml
forward:
  strategy: until_success    # 可选，默认 until_success，取值：until_success | all
  rules:
    - name_mark: default_rule       # 必填，规则标识；作为 destination name_mark 的前缀
      strategy: until_success       # 可选，覆盖 forward.strategy
      filters:                      # 可选；多个 filter 之间为 AND
        - type: and                 # and | or | selector
          match:
            receiver: "17112345678|10086"   # regex.match（从开头匹配）
            sender: "10086"
        - type: selector            # 判断某 key 是否有值
          match:
            code: true              # true/false
      destinations:                 # 规则命中后投递的目标列表
        - target: bark_test         # 必填，引用 target 名
          name_mark: bark_test      # 可选，默认等于 target；最终为 {rule.name_mark}_{destination.name_mark}
          payload:                  # 可选，进一步覆盖 target/channel 的 payload
            group: msgflow
```

策略 `strategy`：

- `until_success`：按顺序投递，任一目标成功即停止；全部失败触发 alarm
- `all`：全部目标都尝试；存在失败则触发 alarm

过滤器 `filters[].type`：

- `and`：`match` 中所有键都需命中（`regex.match` 从字符串开头匹配）
- `or`：`match` 中任一键命中即可
- `selector`：`match` 的值为 `true/false`，判断 msg 中对应 key 是否存在且为真

过滤器 `match` 可用的 key（短信消息字段）：`sender`、`receiver`、`timestamp`、`time_str`、`text`、`msg`、`code`。

### alarm 异常告警

```yaml
alarm:
  strategy: until_success      # 可选，默认 until_success
  destinations:                # 结构与 forward.rules[].destinations 一致
    - target: tgbot_test
      payload:
        title: "{{source}}: {{error}}"
        body: "{{msg}}\n\n{{traceback}}"
        group: alarm
```

告警在以下场景触发：

- 转发规则按 `strategy` 判定为失败（`until_success` 时全失败、`all` 时有失败）
- 处理短信时抛出异常
- 超过 24 小时未收到任何短信

---

## 模板系统

所有字符串值都会以 `{{var}}` 语法进行渲染。`payload` 字段中的字符串若能被解析为 JSON，会先解析再递归渲染。

### 值条件字典

对任意字段，可以用下列三个 key 的字典代替普通值，按消息类型选择分支：

| 键 | 生效场景 | 说明 |
| --- | --- | --- |
| `$default` | 兜底 | 普通消息 / 无其他分支命中时 |
| `$code` | 含验证码 | 识别到验证码时优先使用 |
| `$alarm` | 告警消息 | alarm 调用时优先使用 |

示例：

```yaml
payload:
  title:
    $default: "{{receiver}} <- {{sender}}"
    $code: "🌀 {{code}}"
    $alarm: "{{source}}: {{error}}"
  body:
    $default: "{{text}}\n{{source}} - {{time_str}}"
    $code: "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{time_str}}"
    $alarm: "{{msg}}\n\n{{traceback}}"
```

> 约束：值条件字典只能包含 `$default`、`$code`、`$alarm` 三个 key；出现其他 key 将被当作普通 dict 处理。

### 可用模板变量

通用（来自短信）：

- `{{sender}}`、`{{receiver}}`
- `{{text}}`、`{{code}}`
- `{{timestamp}}`、`{{time_str}}`
- `{{source}}`（来自 `source` 配置）
- `{{msg}}`（当前处理消息的 JSON 字符串）

alarm 额外：

- `{{error}}`：告警标题信息
- `{{traceback}}`：异常堆栈

出现未知变量将在启动时报错。

---

## 配置合并与优先级

对每个 destination，最终有效配置由以下三层 `deep_merge` 得到（后者覆盖前者）：

```
channel.<channel_name>  <  target.<target_name>  <  forward/alarm.destinations[i]
```

最终 `destination.name_mark` 会被改写为 `{{rule.name_mark}}_{{destination.name_mark}}`，用于进度记录与去重。

每条消息的投递进度会写入 `~/.config/msgflow/record.json`，重启后可从上次位置继续。

---

## 命令行参数

```
python msgflow.py [-d] [-c] [-m [-n N]]
```

| 参数 | 说明 |
| --- | --- |
| `-d`, `--debug` | 启用调试模式：日志 DEBUG、加载 `debug/config.yaml`、异常不吞 |
| `-c`, `--check` | 向所有 `forward` destinations 发送一条测试消息验证可用性 |
| `-m`, `--mock` | 从 [sms/sms.json](./sms/sms.json) 随机抽取若干条短信模拟触发 |
| `-n`, `--num` | 配合 `-m` 使用，模拟消息条数（默认 `2`） |

---

## 完整示例

```yaml
check_interval: 3
source: Macmini

channel:
  bark:
    url: https://api.day.app/notify
  tgbot:
    link_preview_options:
      is_disabled: true

target:
  bark_test:
    channel: bark
    payload:
      device_keys:
        - xxx
      group: msgflow
      icon: https://example.com/icon.png

  pushgo_test:
    channel: pushgo
    channel_id: xxx
    password: xxx

  tgbot_test:
    channel: tgbot
    url: https://api.telegram.org/bot<TOKEN>/sendMessage
    payload:
      chat_id: xxx

  webhook_test:
    channel: webhook
    method: POST
    url: https://webhook.example.com
    headers:
      Content-Type: application/json
    payload:
      key: value
    timeout: 5

  local_notify:
    channel: notification
    payload:
      title: "{{receiver}} <- {{sender}}"
      body: "{{text}}\n{{source}} - {{time_str}}"
      copy: "{{text}}"
      autoCopy: 1

forward:
  strategy: until_success
  rules:
    - name_mark: default_rule
      strategy: until_success
      filters:
        - type: or
          match:
            receiver: "17112345678"
            sender: "10010"
        - type: selector
          match:
            code: true
      destinations:
        - target: bark_test
        - target: tgbot_test
          payload:
            disable_notification: true
        - target: local_notify

alarm:
  strategy: until_success
  destinations:
    - target: tgbot_test
      payload:
        title: "{{source}}: {{error}}"
        body: "{{msg}}\n\n{{traceback}}"
        group: alarm
```

---

## Roadmap

- [x] 实时读取短信数据库（`~/Library/Messages/chat.db`）
- [x] 中文(简/繁)、英文验证码自动识别
- [x] 多通道推送：`bark`、`tgbot`、`pushgo`、`lark`、`webhook`、`notification`
- [x] 规则化转发（`and` / `or` / `selector` 过滤器）
- [x] `until_success` / `all` 两种投递策略
- [x] 异常告警通道（alarm），失败自动上报
- [x] 基于值条件字典（`$default` / `$code` / `$alarm`）的模板系统
- [x] pydantic 严格校验配置
- [ ] 通知消息（macOS Notification Center）的监听与转发
- [ ] macOS App 版本，支持自启动、后台运行、日志记录等功能

## Credits

- [TeavenX/py2fa](https://github.com/TeavenX/py2fa)

## License

GPL
