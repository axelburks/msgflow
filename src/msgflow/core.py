import os
import signal
import time, argparse, logging, sys
from pathlib import Path
from . import config
from .common.logging_utils import LOG_FILE_ENV, configure_root_logging, install_unhandled_exception_logging
from .service.flows.sms import SMSFlow
from .service.flows.notify import NotifyFlow
from .service.flows.ipn import IPNFlow
from .rpc.core_rpc import CoreRPCServer
from .service.runtime import CoreRuntime

logger = logging.getLogger(__name__)


def _sms_enabled() -> bool:
    # SMS flow is active only when at least one SMS rule is configured.
    return bool(config.cfg.built_cfg["sms"]["rules"])


def _notify_enabled() -> bool:
    # Notify flow is active only when at least one Notify rule is configured.
    return bool(config.cfg.built_cfg["notify"]["rules"])


def _ipn_enabled() -> bool:
    # iPhone notification flow is active only when at least one IPN rule is configured.
    return bool(config.cfg.built_cfg["ipn"]["rules"])


def _fixture_file_from_dir(fixture_dir: str, kind: str) -> str:
    base_dir = Path(fixture_dir).expanduser()
    candidates = [
        base_dir / kind / f"{kind}.json",
        base_dir / f"{kind}.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(f"fixture for '{kind}' not found under {base_dir}")


def _clear_spinner_line() -> None:
    if not sys.stderr.isatty():
        return
    sys.stderr.write("\r\x1b[K")
    sys.stderr.flush()


def _handle_termination_signal(_signum, _frame) -> None:
    # Route SIGINT/SIGTERM through the normal shutdown path so the transient
    # spinner line is always cleared before the process exits.
    raise KeyboardInterrupt


def _tty_status_label(runtime: CoreRuntime) -> str:
    if runtime.status == "running":
        return "checking"
    if runtime.status == "paused":
        return "paused"
    if runtime.status == "error":
        return "error"
    return runtime.status


class MsgFlowApp(object):
    """
    msgflow application runner. Responsibilities:
      - Build enabled flow instances (SMSFlow / NotifyFlow) from config.
      - Drive each flow's `update_hook` on a fixed interval in a single loop.
    """

    def __init__(self, runtime: CoreRuntime) -> None:
        self.runtime = runtime
        self.check_interval = config.cfg.built_cfg["runtime"]["check_interval"]
        self.flows = []

    def build_flows(self) -> None:
        # Delegate flow construction to the runtime so it can keep RPC alive
        # even when source DB access is missing and surface a structured error.
        self.runtime.ensure_flows_built()
        self.flows = list(self.runtime.flows)

    def run(self) -> None:
        # Main loop: runs flows at `check_interval` while also rendering a
        # lightweight uptime spinner when attached to a TTY.
        self.runtime.bind_loop_thread()
        try:
            self.build_flows()
        except Exception as e:
            logger.error(str(e))
        frame = 0
        tick = 0.2
        spinner = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        start = time.monotonic()
        next_check = start
        is_tty = sys.stderr.isatty()
        self.runtime.maybe_cleanup_history(force=True)
        while True:
            now = time.monotonic()
            command = self.runtime.apply_pending_command()
            if command is not None:
                self.flows = list(self.runtime.flows)
                now = time.monotonic()
            source_checks = self.runtime.pop_pending_source_checks()
            if self.runtime.status == 'running' and self.runtime.error is None and source_checks:
                for flow in self.flows:
                    if flow.KIND in source_checks:
                        flow.update_hook()
                now = time.monotonic()
            if self.runtime.status == 'running' and self.runtime.error is None and now >= next_check:
                if not self.flows:
                    try:
                        self.build_flows()
                    except Exception as e:
                        logger.error(str(e))
                        next_check = now + self.check_interval
                        continue
                for flow in self.flows:
                    flow.update_hook()
                next_check = now + self.check_interval
            if is_tty and self.runtime.status == "running":
                elapsed = int(now - start)
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                status_label = _tty_status_label(self.runtime)
                prefix = spinner[frame % len(spinner)]
                frame += 1
                sys.stderr.write(f'\r{prefix} uptime {h:02d}:{m:02d}:{s:02d} {status_label}')
                sys.stderr.flush()
            elif is_tty:
                _clear_spinner_line()
            if is_tty:
                sleep_for = tick
            else:
                sleep_for = min(self.check_interval, max(tick, next_check - time.monotonic()))
            self.runtime.wait_for_control_signal(sleep_for)


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    format_text = (
        ('\r\x1b[K' if sys.stderr.isatty() else '')
        + (
            '%(asctime)s - %(name)s - %(levelname)-5s - %(message)s'
            if debug
            else '%(asctime)s - core - %(levelname)-5s - %(message)s'
        )
    )
    formatter = logging.Formatter(format_text)
    log_file = os.environ.get(LOG_FILE_ENV)
    configure_root_logging(
        level=level,
        formatter=formatter,
        log_path=Path(os.path.expanduser(log_file)) if log_file else None,
    )
    install_unhandled_exception_logging(logger)


def main() -> None:
    parser = argparse.ArgumentParser(description="Running config for msgflow")
    parser.add_argument('-d', '--debug', action='store_true', help='debug mode: with debug config')
    parser.add_argument('-c', '--check', action='store_true', help='check mode: validate notification channels')
    parser.add_argument('-m', '--mock', action='store_true', help='mock mode: simulate message receiving')
    parser.add_argument('-n', '--num', type=int, default=2, help='number of messages to simulate')
    parser.add_argument(
        '--fixture-file',
        help='optional JSON fixture file for mock mode; requires --kind sms, notify or ipn',
    )
    parser.add_argument(
        '--fixture-dir',
        help='fixture directory for mock mode; with --kind all it must contain sms/sms.json, notify/notify.json and ipn/ipn.json when enabled',
    )
    parser.add_argument(
        '-k', '--kind',
        choices=['sms', 'notify', 'ipn', 'all'],
        default='all',
        help='target kind for check/mock: sms | notify | ipn | all (default: all)',
    )
    args = parser.parse_args()

    # Logging format: the leading `\r\x1b[K` clears the spinner line when
    # running in a TTY so log messages don't overlap with the spinner.
    _configure_logging(debug=args.debug)
    signal.signal(signal.SIGINT, _handle_termination_signal)
    signal.signal(signal.SIGTERM, _handle_termination_signal)

    try:
        config.cfg = config.Config(debug=args.debug)
    except Exception as e:
        # In debug mode we want the full traceback; in normal mode emit a
        # single-line error and exit so log output stays clean.
        if args.debug:
            raise
        logger.error(str(e))
        sys.exit(1)

    runtime = CoreRuntime()
    config.cfg.runtime = runtime

    if args.check:
        # Check mode: synthesize a "check passed" message to every destination
        # so misconfigured channels fail fast instead of at first real message.
        if args.kind in ('sms', 'all') and _sms_enabled():
            SMSFlow().check_destinations()
        if args.kind in ('notify', 'all') and _notify_enabled():
            NotifyFlow().check_destinations()
        if args.kind in ('ipn', 'all') and _ipn_enabled():
            IPNFlow(start_watcher=False).check_destinations()
        sys.exit(0)

    if args.mock:
        # Mock mode: replay sample messages through the full pipeline.
        if args.kind == 'all':
            if not args.fixture_dir:
                logger.error('--kind all with -m requires --fixture-dir')
                sys.exit(1)
            sms_fixture_file = _fixture_file_from_dir(args.fixture_dir, 'sms') if _sms_enabled() else None
            notify_fixture_file = _fixture_file_from_dir(args.fixture_dir, 'notify') if _notify_enabled() else None
            ipn_fixture_file = _fixture_file_from_dir(args.fixture_dir, 'ipn') if _ipn_enabled() else None
        else:
            if args.fixture_file and args.fixture_dir:
                logger.error('use only one of --fixture-file or --fixture-dir')
                sys.exit(1)
            if args.fixture_file:
                selected_fixture_file = args.fixture_file
            elif args.fixture_dir:
                selected_fixture_file = _fixture_file_from_dir(args.fixture_dir, args.kind)
            else:
                logger.error('-m requires --fixture-file or --fixture-dir')
                sys.exit(1)
        if args.kind in ('sms', 'all') and _sms_enabled():
            SMSFlow().mock_to_forward(args.num, fixture_file=sms_fixture_file if args.kind == 'all' else selected_fixture_file)
        if args.kind in ('notify', 'all') and _notify_enabled():
            NotifyFlow().mock_to_forward(args.num, fixture_file=notify_fixture_file if args.kind == 'all' else selected_fixture_file)
        if args.kind in ('ipn', 'all') and _ipn_enabled():
            IPNFlow(start_watcher=False).mock_to_forward(args.num, fixture_file=ipn_fixture_file if args.kind == 'all' else selected_fixture_file)
        sys.exit(0)

    rpc_server = CoreRPCServer(runtime)
    try:
        rpc_server.start()
        runtime.rpc_server = rpc_server
        MsgFlowApp(runtime).run()
    except KeyboardInterrupt:
        _clear_spinner_line()
        logger.info("stopped")
        return
    finally:
        rpc_server.stop()
        runtime.rpc_server = None


if __name__ == '__main__':
    main()
