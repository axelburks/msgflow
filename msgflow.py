import os
import yaml
import logging
import platform
import time
import argparse

from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler

from emailflow import EmailFlow
from smsflow import SMSFlow

class MSGFLOW(object):
    def __init__(self, mode="release"):
        self.scheduler = BackgroundScheduler()
        self.app_scheduler = BackgroundScheduler()
        self.email_list = []
        self.mode = mode
    
    def run(self):
        config_dir = '~/config/msgflow'
        config_file = "config.yaml" if self.mode == "release" else "config_debug.yaml"
        last_fwd_time_file = "last_fwd_time.json" if self.mode == "release" else "last_fwd_time_debug.json"
        config_file_path = f"{config_dir}/{config_file}"
        last_fwd_time_file_path = f"{config_dir}/{last_fwd_time_file}"
        with open(os.path.expanduser(config_file_path), 'r') as fp:
            config = yaml.safe_load(fp)
        last_fwd_time_file_path = os.path.expanduser(last_fwd_time_file_path)

        db_file = os.path.expanduser('~/Library/Messages/chat.db')

        trigger = IntervalTrigger(seconds=3)
        if 'email' in config:
          for i in config['email']:
              self.email_list.append(EmailFlow(i['username'], i['password'], i.get('pop_server', 'pop.' + i['username'].split('@')[1])))
          for i in self.email_list:
              self.scheduler.add_job(i.update_hook, trigger)
        
        fwd_opt = config.get('forward', {})
        self.smsflow = SMSFlow(db_file, fwd_opt, last_fwd_time_file_path)
        # self.scheduler.add_job(self.smsflow.update_hook, trigger)
        # self.scheduler.start()
        # 临时改为while循环，规避scheduler无法定时执行的问题
        while True:
            self.smsflow.update_hook()
            time.sleep(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Running config for msgflow")
    parser.add_argument("--mode", type=str, default="release", help="running mode, default is release")
    args = parser.parse_args()
    
    logging.basicConfig(level = logging.INFO if args.mode == "release" else logging.DEBUG, 
                        format = '%(asctime)s - %(processName)s - %(lineno)d - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)

    app = MSGFLOW(mode=args.mode)
    app.run()

