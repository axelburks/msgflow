import os
import yaml
import logging
import platform
import time

import rumps
import darkdetect
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler

from emailflow import EmailFlow
from smsflow import SMSFlow

rumps.debug_mode(True)

class MSGFLOW(object):
    def __init__(self):
        self.sys_theme = darkdetect.theme()
        icon_file = self.get_menu_icon()
        self.app = rumps.App('MSGFLOW', icon = icon_file)
        self.task_status = rumps.MenuItem(title = '- 监听状态：开启', callback = None)
        self.notification_status = rumps.MenuItem(title = '- 通知状态：开启', callback = None)
        self.clipboard_status = rumps.MenuItem(title = '- 剪切板状态：开启', callback = None)
        self.task_button = rumps.MenuItem(title = '开/关 监听任务', callback = self.switch_task)
        self.notification_button = rumps.MenuItem(title = '开/关 通知', callback = self.switch_notification)
        self.clipboard_button = rumps.MenuItem(title = '开/关 剪切板', callback = self.switch_clipboard)
        self.task_status.state = 1
        self.notification_status.state = 1
        self.clipboard_status.state = 1
        self.app.menu = [self.task_status, self.notification_status, self.clipboard_status, self.task_button, self.notification_button, self.clipboard_button]
        self.scheduler = BackgroundScheduler()
        self.app_scheduler = BackgroundScheduler()
        self.email_list = []

    def switch_task(self, _):
        if self.task_status.state == 1:
            self.task_status.title = '- 监听状态：关闭'
            self.task_status.state = 0
            self.switch_notification('off')
            self.switch_clipboard('off')
            self.scheduler.pause()
        else:
            self.task_status.title = '- 监听状态：开启'
            self.task_status.state = 1
            self.switch_notification('on')
            self.switch_clipboard('on')
            self.scheduler.resume()

    def switch_notification(self, aciton_type = None):
        if self.notification_status.state == 1 or aciton_type == 'off':
            self.notification_status.title = '- 通知状态：关闭'
            self.notification_status.state = 0
            self.smsflow.notify.status = 0
            for i in self.email_list:
                i.notify.status = 0
        else:
            self.notification_status.title = '- 通知状态：开启'
            self.notification_status.state = 1
            self.smsflow.notify.status = 1
            for i in self.email_list:
                i.notify.status = 1
    
    def switch_clipboard(self, aciton_type = None):
        if self.clipboard_status.state == 1 or aciton_type == 'off':
            self.clipboard_status.title = '- 剪切板状态：关闭'
            self.clipboard_status.state = 0
            self.smsflow.clipboard.status = 0
            for i in self.email_list:
                i.clipboard.status = 0
        else:
            self.clipboard_status.title = '- 剪切板状态：开启'
            self.clipboard_status.state = 1
            self.smsflow.clipboard.status = 1
            for i in self.email_list:
                i.clipboard.status = 1
            
    def get_menu_icon(self):
        os_version = platform.platform().split('-')[1].replace('.', '')
        if int(os_version) < 1016:
            return os.path.join('statics', 'light.png' if self.sys_theme == 'Dark' else 'dark.png')
        else:
            return os.path.join('statics', 'light.png')
    
    def update_menu_icon(self):
        if self.sys_theme != darkdetect.theme():
            self.sys_theme = darkdetect.theme()
            self.app.icon = self.get_menu_icon()
    
    def run(self):
        with open(os.path.expanduser('~/msgflow/config.yaml'), 'r') as fp:
            config = yaml.safe_load(fp)
        last_fwd_time_file = os.path.expanduser('~/msgflow/last_fwd_time.json')

        db_file = os.path.expanduser('~/Library/Messages/chat.db')

        trigger = IntervalTrigger(seconds=3)
        if 'email' in config:
          for i in config['email']:
              self.email_list.append(EmailFlow(i['username'], i['password'], i.get('pop_server', 'pop.' + i['username'].split('@')[1])))
          for i in self.email_list:
              self.scheduler.add_job(i.update_hook, trigger)
        
        fwd_opt = config.get('forward', {})
        self.smsflow = SMSFlow(db_file, fwd_opt, last_fwd_time_file)
        # self.scheduler.add_job(self.smsflow.update_hook, trigger)
        # self.scheduler.start()
        # 临时改为while循环，规避scheduler无法定时执行的问题
        while True:
            self.smsflow.update_hook()
            time.sleep(3)

        # trigger = IntervalTrigger(seconds=2)
        # self.app_scheduler.add_job(self.update_menu_icon, trigger)
        # self.app_scheduler.start()

        self.app.run()


if __name__ == '__main__':
    logging.basicConfig(level = logging.INFO, format = '%(asctime)s - %(processName)s - %(lineno)d - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)

    app = MSGFLOW()
    app.run()

