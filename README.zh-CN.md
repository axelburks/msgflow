# MsgFlow

简体中文 | [English](./README.md)

MsgFlow 是一个 macOS 消息转发 App。它会监听设备收到的短信和通知消息，并支持转发到 Bark、Telegram、飞书、PushGo、Webhook、macOS 通知或显示浮窗，同时支持规则匹配和模板渲染。

## 主要特性

- **多消息源**：读取 `~/Library/Messages/chat.db` 中的短信/iMessage，以及 `~/Library/Group Containers/group.com.apple.usernoted/db2/db` 中的 macOS 通知记录。
- **验证码识别**：支持中文简体、中文繁体和英文验证码识别，并可为验证码单独渲染模板。
- **规则化转发**：通过 `and`、`or`、`selector` 过滤器，按正则和消息字段路由到不同目标。
- **多通道投递**：支持 `bark`、`tgbot`、`pushgo`、`lark`、`webhook`、`notification`、`floating`。
- **原生 macOS App**：提供菜单栏、权限引导、监听启停、开机启动、记录窗口、配置查看、本地通知和验证码浮窗。
- **可靠状态记录**：使用 SQLite 保存消息记录、运行记录和每个目标的游标，确保不会遗漏未运行期间收到的消息。
- **重放与排查**：支持对历史消息重新匹配并发送、单目标重发、删除记录、查看最终生效配置和编辑游标。

## 运行要求

- macOS；源码运行需要 Python 3.10+。
- 监听进程需要「完全磁盘访问权限」，否则无法读取短信和通知记录。
- 使用浮窗以及 Type/Paste 动作时，需要「辅助功能」权限。
- 如需转发 iPhone 短信，需要让短信出现在 Mac 的 Messages 中，例如启用 iCloud Messages 或短信转发。
- 如需转发通知，需要目标通知已经出现在 macOS 通知中心。

## 安装

### Homebrew App

推荐优先使用 App 版本，因为它提供浮窗、输入验证码、权限引导和查看历史记录。

```bash
brew tap axelburks/tap
brew install --cask msgflow-app
```

打开 `msgflow.app`，按引导授权，然后从菜单栏打开配置目录。

### Homebrew CLI

如果你更希望把监听器作为后台服务运行，可以安装 CLI。

```bash
brew tap axelburks/tap
brew install msgflow
brew services start msgflow
```

### 源码运行

```bash
git clone https://github.com/axelburks/msgflow.git
cd msgflow
make install
```

启动 Core 和 App：

```bash
make run-core
make run-app
```

贡献者环境、本地验证、打包和发布说明见 [Development](./docs/development.md)。

## 快速开始

创建 `~/.config/msgflow/config.yaml`：

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

启动 msgflow.app 即可开始监听和转发消息。

## 配置概览

MsgFlow 使用 YAML 配置，默认路径为 `~/.config/msgflow/config.yaml`。Debug 模式会读取 `~/.config/msgflow/debug/config.yaml`。

主要配置块：

- `target`：命名转发目标，每个目标指定一个 channel。
- `sms.rules`：短信/iMessage 转发规则。
- `notify.rules`：macOS 通知记录转发规则。
- `alarm.destinations`：投递失败或消息源长时间静默时使用的告警目标。
- `channel`：可选的通道公共默认配置。
- `app`：可选的 App 历史记录保留策略。

每个 destination 的最终配置由三层合并得到，后者覆盖前者：

```text
channel.<channel> < target.<name> < rule.destinations[]
```

完整配置结构、模板变量、过滤器、命令行参数和完整示例见 [配置文档](./docs/configuration.zh-CN.md)。

## 示例：转发验证码到 Bark 和浮窗

```yaml
source: MacBook

target:
  bark_phone:
    channel: bark
    payload:
      device_keys:
        - YOUR_BARK_KEY
      group: msgflow

  code_panel:
    channel: floating

sms:
  strategy: until_success
  rules:
    - name_mark: verification_codes
      filters:
        - type: selector
          match:
            code: true
      destinations:
        - target: code_panel
        - target: bark_phone

alarm:
  destinations:
    - target: bark_phone
```

## App 能力

- 权限引导：辅助功能、完全磁盘访问。
- 菜单栏操作：Start/Pause、Reload Config、Open Config Folder、Launch at Login、Debug Mode。
- 历史记录窗口：查看短信和通知的处理记录。
- 查询 DSL：按 `sender`、`text`、`kind`、`status`、`trigger`、`rule`、`dest` 等字段搜索。
- 配置与游标：查看最终生效配置，编辑每类消息源的目标游标。
- 重放操作：Rematch & Send、Resend Destination、Delete。
- 本地呈现：macOS 原生通知、带 Type/Paste 的验证码浮窗。

## 注意事项

- MsgFlow 只读取本机 macOS 数据库，不会修改 Messages 或通知中心数据库。
- 首次启动会从每个数据库当前末尾开始监听，不会自动回放历史消息。
- 远端通道游标会持久化；本地通道（`notification`、`floating`）不会持久化游标。
- 未签名或未公证的构建可能触发 Gatekeeper 提示。

## Roadmap

- [x] 实时读取 macOS Messages 短信/iMessage
- [x] 中文简体、中文繁体、英文验证码自动识别
- [x] 转发到 Bark、Telegram Bot、PushGo、飞书、Webhook、本地通知
- [x] 基于 `and`、`or`、`selector` 的规则化转发
- [x] `until_success` / `all` 两种投递策略
- [x] 支持异常告警通知(alarm)
- [x] 基于 `$default`、`$code`、`$alarm` 的条件模板
- [x] Pydantic 严格配置校验
- [x] 支持监听 macOS 通知消息
- [x] App 版本，初版支持菜单栏、切换监听状态、运行历史窗口等基础功能
- [x] App 支持浮窗显示消息、验证码，支持点击输入/粘贴指定内容
- [x] App 支持记录多重筛选、重新匹配、单目标重发、删除记录、查看配置和编辑游标
- [ ] App 支持主窗口自动刷新记录
- [ ] rpc 更换为 unix socket
- [ ] 支持监听来自 iPhone 的通知
- [ ] App 支持多语言界面
- [ ] App 自动签名构建产物

## 文档

- [配置文档](./docs/configuration.zh-CN.md)：完整用户配置参考和示例。
- [Development](./docs/development.md)：源码运行、本地验证、构建产物和架构说明。

## Credits

- [TeavenX/py2fa](https://github.com/TeavenX/py2fa)。

## License

GPL-3.0-only
