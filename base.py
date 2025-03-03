import os
import logging
import urllib.parse
import subprocess
import html
import regex
import json

import requests
import pyperclip

class Base(object):

    def __init__(self):
        self.logging = logging.getLogger(__name__)
        
    def get_code_from_msg(self, msg):
        msg_code = None
        if not msg:
            return None
        
        pattern_flags = r"(?<!回复|回覆|获取|獲取)((验证|授权|校验|检验|确认|激活|动态|安全|登入|认证|识别|交易|短信|授权|随机|一次性)(代?码|口令|密码|编码)|(驗證|授權|校驗|檢驗|確認|激活|動態|安全|登入|認證|識別|交易|短信|授權|隨機|一次性)(代?碼|口令|密碼|編碼)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode)"
        pattern_captchas = r"(?<!(联系|聯繫|结尾|結尾|尾号|尾號|尾4位|ending |[A-Za-z0-9]))([0-9-]{4,8})(?![A-Za-z0-9]|\]?(-| -))"

        msg_escaped = regex.sub(r'((https?|ftp|file):\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|$!:,.;]*[A-Z0-9+&@#\/%=~_|$]|\n', ' ', msg, flags=regex.I)

        match_flags = regex.search(pattern_flags, msg_escaped, flags=regex.I)
        matches_captchas = regex.findall(pattern_captchas, msg_escaped)
        
        if match_flags and matches_captchas:
            flag_index = msg_escaped.find(match_flags.group())
            closest_captcha = min(matches_captchas, key=lambda x: abs(msg_escaped.find(x[1]) - flag_index))[1]
            msg_code = closest_captcha
        
        return msg_code

    def notify_to_bark(self, dest, title, msg, code=None):
        try:
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
        except Exception as e:
            return False, str(e)
            
    def notify_to_tgbot(self, dest, title, msg, code=None):
        try:
            tgbot_url = dest['server_url']
            title = html.escape(title)
            msg = html.escape(msg)
            title = title.replace(code, f"<code>{code}</code>") if code else title
            msg = msg.replace(code, f"<code>{code}</code>") if code else msg
            tgbot_body = {
                "text": f"{title}\n{msg}",
                "parse_mode": "HTML",
            }
            unneedkeys = ['name_mark', 'filters', 'server_url', 'template']
            tgbot_body.update({key: dest[key] for key in dest if key not in unneedkeys})            
            self.logging.info(f"Sending to tgbot dest: {dest.get('name_mark', '')}")
            tgbot_res = requests.post(tgbot_url, json=tgbot_body)
            if tgbot_res.status_code != 200:
                return False, f"Telegram API Error: {tgbot_res.text}"
            else:
                return True, tgbot_res.text
        except Exception as e:
            return False, str(e)

    def notification(self, title, msg):
        subprocess.run([
            'osascript', '-e', f'display notification "{msg}" with title "{title}"'
        ], check=True)

    def save_to_clipboard(self, code):
        pyperclip.copy(str(code))
        
        
if __name__ == '__main__':
    try:
        with open(os.path.expanduser(f"./sms/sms.json"), 'r') as f:
            msg_file = json.load(f)
        test = Base()
        for msg in msg_file:
            code = test.get_code_from_msg(msg['text'])
            if code != msg['code']:
                print(f"text: {msg['text']}, expected: {msg['code']}, got: {code}")
    except FileNotFoundError:
        print("msg_file not found.")