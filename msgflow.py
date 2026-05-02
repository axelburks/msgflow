import time, argparse, logging, sys
import config
from smsflow import SMSFlow


class MSGFLOW(object):
    def __init__(self):
        self.check_interval = config.cfg.built_cfg.get('check_interval')

    def run(self):
        self.smsflow = SMSFlow()
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
                if not is_tty and count % 300 == 1:
                    logging.info(f'checking #{count}')
                self.smsflow.update_hook()
                next_check = now + self.check_interval
            if is_tty:
                elapsed = int(now - start)
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                sys.stderr.write(f'\r{spinner[frame % len(spinner)]} uptime {h:02d}:{m:02d}:{s:02d} checking')
                sys.stderr.flush()
                frame += 1
            time.sleep(tick if is_tty else self.check_interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Running config for msgflow")
    parser.add_argument('-d', '--debug', action='store_true', help='debug mode: with debug config')
    parser.add_argument('-c', '--check', action='store_true', help='check mode: validate notification channels')
    parser.add_argument('-m', '--mock', action='store_true', help='mock mode: simulate sms forwarding from sms/sms.json')
    parser.add_argument('-n', '--num', type=int, default=2, help='number of sms messages to simulate')
    args = parser.parse_args()

    logging.basicConfig(
        level = logging.DEBUG if args.debug else logging.INFO,
        format = ('\r\x1b[K' if sys.stderr.isatty() else '') + '%(asctime)s - %(name)s - %(levelname)-5s - %(message)s'
    )
    try:
        config.cfg = config.Config(debug=args.debug)
    except Exception as e:
        if args.debug:
            raise
        logging.error(str(e))
        sys.exit(1)

    if args.check:
        SMSFlow().check_forward_destinations()
        sys.exit(0)

    if args.mock:
        SMSFlow().mock2notify(args.num)
        sys.exit(0)
    
    app = MSGFLOW()
    app.run()