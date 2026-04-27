import time, argparse, logging, sys
# from apscheduler.triggers.interval import IntervalTrigger
# from apscheduler.schedulers.background import BackgroundScheduler

from config import config
from smsflow import SMSFlow
# from emailflow import EmailFlow


class MSGFLOW(object):
    def __init__(self):
        self.check_interval = config.user_config.get('check_interval') or 3
        # self.scheduler = BackgroundScheduler()
        # self.app_scheduler = BackgroundScheduler()
        # self.email_list = []

    def run(self):
        # trigger = IntervalTrigger(seconds=self.check_interval)
        # 
        # if 'email' in config:
        #   for i in config['email']:
        #       self.email_list.append(EmailFlow(i['username'], i['password'], i.get('pop_server', 'pop.' + i['username'].split('@')[1])))
        #   for i in self.email_list:
        #       self.scheduler.add_job(i.update_hook, trigger)
        
        self.smsflow = SMSFlow()
        # self.scheduler.add_job(self.smsflow.update_hook, trigger)
        # self.scheduler.start()

        # 临时改为while循环，规避scheduler无法定时执行的问题
        count = 0
        while True:
            count = (count % 60) + 1
            if count == 1: logging.info('checking')
            self.smsflow.update_hook()
            time.sleep(self.check_interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Running config for msgflow")
    parser.add_argument('-d', '--debug', action='store_true', help='debug mode: with debug config')
    parser.add_argument('-c', '--check', action='store_true', help='check mode: validate notification channels')
    parser.add_argument('-m', '--mock', action='store_true', help='mock mode: simulate sms forwarding from sms/sms.json')
    parser.add_argument('-n', '--num', type=int, default=2, help='number of sms messages to simulate')
    args = parser.parse_args()

    log_level = logging.INFO
    if args.debug:
        log_level = logging.DEBUG
        config.debug_mode = True
    logging.basicConfig(
        level = log_level, 
        format = '%(asctime)s - %(name)s - %(levelname)-5s - %(message)s'
    )

    if args.check:
        SMSFlow().check_forward_destinations()
        sys.exit(0)

    if args.mock:
        SMSFlow().mock2notify(args.num)
        sys.exit(0)
    
    app = MSGFLOW()
    app.run()