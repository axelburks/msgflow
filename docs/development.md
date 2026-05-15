# Development

This guide is for contributors and maintainers who run MsgFlow from source or build release artifacts locally.

## Local Environment

Use the Make targets to create a project-local virtual environment and install dependencies:

```bash
make install
```

Install test-only dependencies before running pytest:

```bash
make install-test
```

`make install-build` also installs PyInstaller.

## Entry Points

| Path | Purpose |
| --- | --- |
| `app.py` | Direct-run app wrapper for local development, VS Code, and PyInstaller. |
| `core.py` | Direct-run core wrapper for local development, VS Code, and PyInstaller. |
| `src/msgflow/app.py` | Package app entry point used by `msgflow-app`. |
| `src/msgflow/core.py` | Package core entry point used by `msgflow`. |
| `src/msgflow/service/` | Runtime, flows, channels, history, and replay logic. |
| `src/msgflow/ui/` | AppKit UI, setup, menu bar, main window, floating panel. |
| `src/msgflow/rpc/` | Local Unix socket RPC between app, core, and app-backed channels. |
| `tests/fixtures/` | Explicit mock data for local development. |

## Run From Source

Core service:

```bash
make run-core
```

Debug mode, using `~/.config/msgflow/debug/config.yaml`:

```bash
make run-core-debug
```

App UI:

```bash
make run-app
```

Mock one SMS fixture:

```bash
make mock-sms
```

Mock all fixture kinds:

```bash
make mock-all
```

Make shortcuts:

```bash
make test
make verify
make check
make mock-sms
make mock-notify
make mock-all
make run-core
make run-core-debug
make run-app
```

## Verification

Run the pytest suite:

```bash
make test
```

Run one file or subdirectory by overriding `TEST`:

```bash
make test TEST=tests/test_channels.py
```

Use verbose output while debugging:

```bash
make test-verbose
```

The pytest suite should not send real network requests or trigger local UI side effects. Tests mock HTTP requests, app RPC calls, clipboard writes, `osascript`, and system database probes.

Compile-time verification:

```bash
make verify
```

This runs:

```bash
python3 -m compileall app.py core.py src scripts/release.py
```

Channel check against your real config:

```bash
make check
```

Mock runs require explicit fixtures and do not rely on bundled package data.

## VS Code

`.vscode/launch.json` includes launch configurations for:

- `core-normal`
- `core-check`
- `core-mock`
- `core-debug`
- `core-check-debug`
- `core-mock-debug`
- `app-ui`

## Local Build

Install build dependencies:

```bash
.venv/bin/python -m pip install pyinstaller
```

Build all release artifacts:

```bash
.venv/bin/python scripts/release.py --repo <owner>/<repo>
```

Equivalent Make command:

```bash
make build
```

The default version comes from `[project].version` in `pyproject.toml`. Override it when needed:

```bash
.venv/bin/python scripts/release.py --version 0.2.0 --repo <owner>/<repo>
make build VERSION=0.2.0
```

Outputs:

```text
dist/msgflow/msgflow
dist/msgflow-core/msgflow-core
dist/msgflow.app
release/msgflow-<version>-macos-<arch>.tar.gz
release/msgflow-app-<version>-macos-<arch>.zip
release/homebrew/Formula/msgflow.rb
release/homebrew/Casks/msgflow-app.rb
```

## Smoke Checks

```bash
make smoke-cli
make smoke-core
make smoke-app
make smoke-all
```

`smoke-cli` and `smoke-core` run packaged binaries. `smoke-app` opens the packaged app.

## Packaging Notes

- `scripts/release.py` writes PyInstaller cache to `.pyinstaller-cache/`.
- `dist/` contains raw PyInstaller outputs.
- `release/` contains final distributable archives and rendered Homebrew files.
- `tests/fixtures/` are not bundled; `msgflow --mock` must receive `--fixture-file` or `--fixture-dir` explicitly.
- `msgflow.app` embeds `msgflow-core` as `Contents/MacOS/msgflow-core`.
- Codesign runs only when `APPLE_SIGNING_IDENTITY` is set.
- Notarization runs only when `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID` are set.

## Architecture Notes

- Core and UI communicate through a local Unix socket at `<config-dir>/run/core.sock`.
- App-backed channels (`notification`, `floating`) call the app RPC server through `<config-dir>/run/app.sock`.
- The app can manage a bundled core process or connect to an external core if it is already running.
- Source database access is probed at runtime so permission problems can be shown as structured UI errors.
- SQLite history stores message records, run records, cursor state, and app history data.
