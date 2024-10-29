import os
import logging
import urllib.parse

import rumps
import requests
import pyperclip

class Base(object):

    def __init__(self):
        self.logging = logging.getLogger(__name__)
        self.notify = Switcher()
        self.clipboard = Switcher()

    def notify_to_bark(self, dest, title, msg, code=None):
        if self.notify.status:
            autoCopy = 1 if code else 0
            copy = code if code else f"{title}\n{msg}"
            level = 'timeSensitive' if code else 'active'
            bark_url = dest['server_url']
            bark_body = {
                "title": title,
                "body": msg,
                "level": level,
                "autoCopy": autoCopy,
                "copy": copy,
            }
            unneedkeys = ['name_mark', 'filters', 'server_url', 'template']
            bark_body.update({key: dest[key] for key in dest if key not in unneedkeys})
            self.logging.info(f"Sending to bark dest: {dest.get('name_mark', '')}")
            bark_res = requests.post(bark_url, json=bark_body)
            if bark_res.status_code != 200:
                return False, f"Bark API Error: {bark_res.text}"
            else:
                return True, bark_res.text
            
    def notify_to_tgbot(self, dest, title, msg, code=None):
        self.logging.debug(self.notify.status)
        if self.notify.status:
            tgbot_url = dest['server_url']
            tgbot_body = {
                "text": f"{title}\n{msg}",
            }
            unneedkeys = ['name_mark', 'filters', 'server_url', 'template']
            tgbot_body.update({key: dest[key] for key in dest if key not in unneedkeys})            
            self.logging.info(f"Sending to tgbot dest: {dest.get('name_mark', '')}")
            tgbot_res = requests.post(tgbot_url, json=tgbot_body)
            if tgbot_res.status_code != 200:
                return False, f"Telegram API Error: {tgbot_res.text}"
            else:
                return True, tgbot_res.text

    def notification(self, title, msg):
        self.logging.debug(self.notify.status)
        if self.notify.status:
            cmd = '''/usr/bin/osascript -e 'display notification \"{msg}\" with title \"{title}\"' '''.format(title = title, msg = msg)
            os.system(cmd)
            # 切换到app通知
            # rumps.notification(title = title, subtitle = msg, message = '')

    def save_to_clipboard(self, code):
        self.logging.debug(self.clipboard.status)
        if self.clipboard.status:
            pyperclip.copy(str(code))

class Switcher(object):
    
    def __init__(self):
        self._status = 1
    
    @property
    def status(self):
        return self._status
    
    @status.setter
    def status(self, status):
        self._status = status