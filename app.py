import time, argparse, logging, sys
import config
from smsflow import SMSFlow
from notifyflow import NotifyFlow

logger = logging.getLogger(__name__)


def _sms_enabled() -> bool:
    # SMS flow is active only when at least one SMS rule is configured.
    return bool(config.cfg.built_cfg.get('sms', {}).get('rules'))


def _notify_enabled() -> bool:
    # Notify flow is active only when at least one Notify rule is configured.
    return bool(config.cfg.built_cfg.get('notify', {}).get('rules'))


class MsgFlowApp(object):
    """
    msgflow application runner. Responsibilities:
      - Build enabled flow instances (SMSFlow / NotifyFlow) from config.
      - Drive each flow's `update_hook` on a fixed interval in a single loop.
    """

    def __init__(self) -> None:
        self.check_interval = config.cfg.built_cfg.get('check_interval')
        self.flows = []

    def build_flows(self) -> None:
        # Instantiate only the flows that have rules configured so we never
        # open system databases we don't actually need.
        if _sms_enabled():
            self.flows.append(SMSFlow())
        if _notify_enabled():
            self.flows.append(NotifyFlow())
        if not self.flows:
            logger.error('❌ no sms/notify rules configured, nothing to monitor')
            sys.exit(1)

    def run(self) -> None:
        # Main loop: runs flows at `check_interval` while also rendering a
        # lightweight uptime spinner when attached to a TTY.
        self.build_flows()
        count = 0
        frame = 0
        tick = 0.2
        spinner = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        start = time.monotonic()
        next_check = start
        is_tty = sys.stderr.isatty()
        while True:
            now = time.monotonic()
            if now >= next_check:
                count += 1
                # When not a TTY (e.g. launchd / log file), emit a heartbeat
                # line roughly every 300 ticks so the log shows liveness.
                if not is_tty and count % 300 == 1:
                    logger.info(f'checking #{count}')
                for flow in self.flows:
                    flow.update_hook()
                next_check = now + self.check_interval
            if is_tty:
                elapsed = int(now - start)
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                sys.stderr.write(f'\r{spinner[frame % len(spinner)]} uptime {h:02d}:{m:02d}:{s:02d} checking')
                sys.stderr.flush()
                frame += 1
            # Sleep a short `tick` in TTY mode (for spinner animation)
            # otherwise sleep a full `check_interval` to save CPU.
            time.sleep(tick if is_tty else self.check_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Running config for msgflow")
    parser.add_argument('-d', '--debug', action='store_true', help='debug mode: with debug config')
    parser.add_argument('-c', '--check', action='store_true', help='check mode: validate notification channels')
    parser.add_argument('-m', '--mock', action='store_true', help='mock mode: simulate message receiving')
    parser.add_argument('-n', '--num', type=int, default=2, help='number of messages to simulate')
    parser.add_argument(
        '-k', '--kind',
        choices=['sms', 'notify', 'all'],
        default='all',
        help='target kind for check/mock: sms | notify | all (default: all)',
    )
    args = parser.parse_args()

    # Logging format: the leading `\r\x1b[K` clears the spinner line when
    # running in a TTY so log messages don't overlap with the spinner.
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format=('\r\x1b[K' if sys.stderr.isatty() else '') + '%(asctime)s - %(name)s - %(levelname)-5s - %(message)s'
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format=('\r\x1b[K' if sys.stderr.isatty() else '') + '%(asctime)s - %(levelname)-5s - %(message)s'
        )

    try:
        config.cfg = config.Config(debug=args.debug)
    except Exception as e:
        # In debug mode we want the full traceback; in normal mode emit a
        # single-line error and exit so log output stays clean.
        if args.debug:
            raise
        logger.error(str(e))
        sys.exit(1)

    if args.check:
        # Check mode: synthesize a "check passed" message to every destination
        # so misconfigured channels fail fast instead of at first real message.
        if args.kind in ('sms', 'all') and _sms_enabled():
            SMSFlow().check_destinations()
        if args.kind in ('notify', 'all') and _notify_enabled():
            NotifyFlow().check_destinations()
        sys.exit(0)

    if args.mock:
        # Mock mode: replay sample messages through the full pipeline.
        if args.kind in ('sms', 'all') and _sms_enabled():
            SMSFlow().mock_to_forward(args.num)
        if args.kind in ('notify', 'all') and _notify_enabled():
            NotifyFlow().mock_to_forward(args.num)
        sys.exit(0)

    MsgFlowApp().run()


if __name__ == '__main__':
    main()
