# MsgFlow

[简体中文](./README.zh-CN.md) | English

MsgFlow is a macOS message forwarding app. It listens for SMS and notification messages received on your device, forwards them to Bark, Telegram, Lark, PushGo, webhooks, macOS notifications, or floating panels, and supports rule matching plus template rendering.

## Highlights

- **Multiple sources**: reads SMS/iMessage from `~/Library/Messages/chat.db`, macOS notification records from `~/Library/Group Containers/group.com.apple.usernoted/db2/db`, and iPhone mirrored notifications from `~/Library/Group Containers/group.com.apple.UserNotifications/Library/UserNotifications/Remote/default`.
- **Code detection**: detects verification codes in Simplified Chinese, Traditional Chinese, and English messages, with dedicated templates for code messages.
- **Rule-based forwarding**: routes messages to different destinations with `and`, `or`, and `selector` filters using regex and message fields.
- **Multiple channels**: supports `bark`, `tgbot`, `pushgo`, `lark`, `webhook`, `notification`, and `floating`.
- **Native macOS app**: provides a menu bar app, permission setup, listener controls, Launch at Login, history window, config viewer, local notifications, and verification-code floating panels.
- **Reliable state tracking**: stores message records, run records, and per-destination cursors in SQLite to ensure messages received while MsgFlow was not running are not missed.
- **Replay and debugging**: supports rematching historical messages, resending one destination, deleting records, viewing the effective config, and editing cursors.

## Requirements

- macOS; Python 3.10+ is required when running from source.
- The listener process needs Full Disk Access, otherwise it cannot read SMS and notification records.
- Accessibility permission is required for floating panels and Type/Paste actions.
- To forward iPhone SMS, the messages must appear in Messages on the Mac, for example through iCloud Messages or Text Message Forwarding.
- To forward macOS notifications, the target notifications must already appear in macOS Notification Center.
- To forward iPhone notifications, iPhone Mirroring notification forwarding must be enabled in macOS and iOS settings.

## Installation

### Homebrew App

The app version is recommended because it provides floating panels, verification-code input actions, permission setup, and history viewing.

```bash
brew install axelburks/tap/msgflow-app
```

Upgrade:

```bash
brew upgrade msgflow-app
```

Open `msgflow.app`, grant the requested permissions, then open the config folder from the menu bar item.

If macOS says `msgflow.app` is damaged or cannot be opened, remove the quarantine flag manually and open it again:

```bash
sudo xattr -dr com.apple.quarantine /Applications/msgflow.app
open /Applications/msgflow.app
```

### Homebrew CLI

Use the CLI if you prefer running the listener as a background service.

```bash
brew install axelburks/tap/msgflow
```

Upgrade:

```bash
brew update && brew upgrade msgflow-app
```

Start the background service:

```bash
brew services start msgflow
```

### From Source

```bash
git clone https://github.com/axelburks/msgflow.git
cd msgflow
make install
```

Run the core and app:

```bash
make run-core
make run-app
```

For contributor setup, local verification, build, and release notes, see [Development](./docs/development.md).

## Quick Start

Create `~/.config/msgflow/config.yaml`:

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

Start `msgflow.app` to begin listening for and forwarding messages.

## Configuration Overview

MsgFlow configuration is YAML and defaults to `~/.config/msgflow/config.yaml`. Debug mode reads `~/.config/msgflow/debug/config.yaml`.

The main blocks are:

- `target`: named forwarding targets, each specifying a channel.
- `sms.rules`: SMS/iMessage forwarding rules.
- `notify.rules`: macOS notification record forwarding rules.
- `ipn.rules`: iPhone mirrored notification forwarding rules.
- `alarm.destinations`: alert destinations used when delivery fails or a source is silent for too long.
- `channel`: optional shared defaults for channels.
- `app`: optional app history retention settings.

Each destination's final config is merged from three layers, where later layers override earlier ones:

```text
channel.<channel> < channel.<channel>.<kind> < target.<name> < rule.destinations[]
```

See [Configuration](./docs/configuration.md) for the full config structure, template variables, filters, command-line options, and complete examples.

## Example: Forward Codes to Bark and a Floating Panel

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

## App Features

- Permission setup: Accessibility and Full Disk Access.
- Menu bar actions: Start/Pause, Reload Config, Open Config Folder, Launch at Login, Debug Mode.
- History window: view processing records for SMS, macOS notifications, and iPhone notifications.
- Query DSL: search by fields such as `sender`, `receiver`, `title`, `subtitle`, `body`, `kind`, `status`, `trigger`, and `code`.
- Config and cursors: view the effective config and edit target cursors per message kind.
- Replay actions: Rematch & Send, Resend Destination, Delete.
- Local presentation: native macOS notifications and verification-code floating panels with Type/Paste actions.

## Important Notes

- MsgFlow only reads local macOS stores; it does not modify Messages, Notification Center, or iPhone notification files.
- On first launch, MsgFlow starts listening from the current tail of each source and does not automatically replay historical messages.
- Remote channel cursors are persisted; local channels (`notification`, `floating`) do not persist cursors.
- Unsigned or non-notarized builds may trigger Gatekeeper warnings.

## Roadmap

- [x] Read SMS/iMessage from macOS Messages in real time
- [x] Automatically detect verification codes in Simplified Chinese, Traditional Chinese, and English
- [x] Forward to Bark, Telegram Bot, PushGo, Lark, Webhook, and local notifications
- [x] Rule-based forwarding with `and`, `or`, and `selector`
- [x] Two delivery strategies: `until_success` / `all`
- [x] Support exception alert notifications (alarm)
- [x] Conditional templates based on `$default`, `$code`, and `$alarm`
- [x] Strict Pydantic config validation
- [x] Support listening to macOS notification messages
- [x] App version with initial support for the menu bar, listener status switching, history window, and other basic features
- [x] App support for floating panels that display messages and verification codes, with click-to-type/paste actions for specified content
- [x] App support for multi-filtering records, rematching, resending a single destination, deleting records, viewing config, and editing cursors
- [x] Use unix sockets for rpc communication
- [x] App support for multilingual UI
- [x] Support listening to notifications from iPhone
- [ ] App support for signing and building the app

## Documentation

- [Configuration](./docs/configuration.md): full user configuration reference and examples.
- [Development](./docs/development.md): source setup, local verification, build artifacts, and architecture notes.

## Credits

- [TeavenX/py2fa](https://github.com/TeavenX/py2fa).

## License

GPL-3.0-only
