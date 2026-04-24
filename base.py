import os, logging, json, html, subprocess
import requests, regex, yaml, pyperclip

config_dir = '~/.config/msgflow'
config_file = 'config.yaml'
record_file = 'record.json'

class Config:
    def __init__(self):
        self._debug_mode = False
        self._update_config()
    
    def _update_config(self):
        self._config_file_path = os.path.expanduser(f"{config_dir}/{config_file}")
        self._record_file_path = os.path.expanduser(f"{config_dir}/{record_file}")
        with open(self._config_file_path, 'r') as fp:
            self._user_config = yaml.safe_load(fp)

    @property
    def debug_mode(self):
        return self._debug_mode
    
    @debug_mode.setter
    def debug_mode(self, value):
        self._debug_mode = value
        if self._debug_mode:
            global config_dir
            config_dir = f"{config_dir}/debug"
        self._update_config()

    @property
    def record_file_path(self):
        return self._record_file_path
    
    @property
    def user_config(self):
        return self._user_config

def channel(name: str):
    def decorator(fn):
        fn._msgflow_channel = name
        return fn
    return decorator

class Base(object):

    def __init__(self):
        self.logging = logging.getLogger(__name__)
        self.channel_notifiers = self._build_channel_notifiers()

    def _build_channel_notifiers(self):
        channel_notifiers = {}
        for attr in dir(self):
            fn = getattr(self, attr, None)
            if not callable(fn):
                continue
            channel_name = getattr(fn, '_msgflow_channel', None)
            if not channel_name:
                continue
            if channel_name in channel_notifiers:
                raise Exception(f"duplicate channel notifier for '{channel_name}'")
            channel_notifiers[channel_name] = fn
        return channel_notifiers
    
    def _format_http_response_text(self, res):
        try:
            data = res.json()
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            text = res.text
            return text
        
    def get_code_from_msg(self, msg):
        code = None
        if not msg:
            return None
        
        pattern_flags = r"(?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|激活|动态|動態|安全|登入|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode)"
        pattern_captchas = r"(?<!(联系|聯繫|结尾|結尾|尾号|尾號|尾4位|ending |[A-Za-z0-9]))([0-9-]{4,8})(?![A-Za-z0-9]|\]?(-| -))"

        msg_escaped = regex.sub(r'((https?|ftp|file):\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|$!:,.;]*[A-Z0-9+&@#\/%=~_|$]|\n', ' ', msg, flags=regex.I)

        match_flags = regex.search(pattern_flags, msg_escaped, flags=regex.I)
        matches_captchas = regex.findall(pattern_captchas, msg_escaped)
        
        if match_flags and matches_captchas:
            flag_index = msg_escaped.find(match_flags.group())
            closest_captcha = min(matches_captchas, key=lambda x: abs(msg_escaped.find(x[1]) - flag_index))[1]
            code = closest_captcha
        
        return code

    @channel('bark')
    def notify_to_bark(self, dest, title, body, code=None):
        dest_mark = f"📣 {dest.get('name_mark')}({dest.get('channel')})"
        try:
            self.logging.info(f"{dest_mark}")
            autoCopy = 1 if code else 0
            copy = code if code else f"{title}\n{body}"
            level = 'timeSensitive' if code else 'active'
            bark_url = dest['url']
            bark_body = {
                "title": title,
                "body": body,
                "level": level,
                "autoCopy": autoCopy,
                "copy": copy,
            }
            unneedkeys = ['name_mark', 'filters', 'url', 'template', 'target', 'channel']
            bark_body.update({key: dest[key] for key in dest if key not in unneedkeys})
            self.logging.debug(f"{dest_mark} body: {json.dumps(bark_body, ensure_ascii=False)}")
            bark_res = requests.post(bark_url, json=bark_body)
            formatted_res_text = self._format_http_response_text(bark_res)
            self.logging.debug(f"{dest_mark} response: {formatted_res_text}")
            if bark_res.status_code != 200:
                return False, f"{dest_mark} error: {formatted_res_text}"
            return True, formatted_res_text
        except Exception as e:
            return False, f"{dest_mark} error: {e}"
        
    @channel('pushgo')
    def notify_to_pushgo(self, dest, title, body, code=None):
        dest_mark = f"🌸 {dest.get('name_mark')}({dest.get('channel')})"
        try:
            
            self.logging.info(f"{dest_mark}")
            pushgo_url = dest['url']
            pushgo_body = {
                "title": title,
                "body": body,
            }
            unneedkeys = ['name_mark', 'filters', 'url', 'template', 'target', 'channel']
            pushgo_body.update({key: dest[key] for key in dest if key not in unneedkeys})
            self.logging.debug(f"{dest_mark} body: {json.dumps(pushgo_body, ensure_ascii=False)}")
            pushgo_res = requests.post(pushgo_url, json=pushgo_body)
            formatted_res_text = self._format_http_response_text(pushgo_res)
            self.logging.debug(f"{dest_mark} response: {formatted_res_text}")
            if pushgo_res.status_code != 200:
                return False, f"{dest_mark} error: {formatted_res_text}"
            return True, formatted_res_text
        except Exception as e:
            return False, f"{dest_mark} error: {e}"
        
    @channel('tgbot')
    def notify_to_tgbot(self, dest, title, body, code=None):
        dest_mark = f"🤖 {dest.get('name_mark')}({dest.get('channel')})"
        try:
            self.logging.info(f"{dest_mark}")
            tgbot_url = dest['url']
            title = html.escape(title)
            body = html.escape(body)
            title = title.replace(code, f"<code>{code}</code>") if code else title
            body = body.replace(code, f"<code>{code}</code>") if code else body
            tgbot_body = {
                "text": f"{title}\n{body}",
                "parse_mode": "HTML",
            }
            unneedkeys = ['name_mark', 'filters', 'url', 'template', 'target', 'channel']
            tgbot_body.update({key: dest[key] for key in dest if key not in unneedkeys})            
            self.logging.debug(f"{dest_mark} body: {json.dumps(tgbot_body, ensure_ascii=False)}")
            tgbot_res = requests.post(tgbot_url, json=tgbot_body)
            formatted_res_text = self._format_http_response_text(tgbot_res)
            self.logging.debug(f"{dest_mark} response: {formatted_res_text}")
            if tgbot_res.status_code != 200:
                return False, f"{dest_mark} error: {formatted_res_text}"
            else:
                return True, formatted_res_text
        except Exception as e:
            return False, f"{dest_mark} error: {e}"

    @channel('lark')
    def notify_to_lark(self, dest, title, body, code=None):
        dest_mark = f"📘 {dest.get('name_mark')}({dest.get('channel')})"
        try:
            self.logging.info(f"{dest_mark}")
            lark_url = dest['url']
            lark_normal_body = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "template": "blue",
                        "title": {
                            "content": title,
                            "tag": "plain_text"
                        }
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "content": body,
                                "tag": "lark_md"
                            }
                        }
                    ]
                }
            }
            lark_code_body = {
                "header": {
                    "template": "green",
                    "title": {
                        "content": title,
                        "tag": "plain_text"
                    }
                },
                "elements": [
                    {
                        "tag": "column_set",
                        "flex_mode": "none",
                        "background_style": "grey",
                        "horizontal_spacing": "default",
                        "columns": [
                            {
                                "tag": "column",
                                "width": "weighted",
                                "weight": 1,
                                "elements": [
                                    {
                                        "tag": "markdown",
                                        "text_align": "center",
                                        "content": f"验证码\n{code}\n"
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "tag": "div",
                        "text": {
                            "content": body,
                            "tag": "lark_md"
                        }
                    }
                ]
            }
            lark_body = lark_code_body if code else lark_normal_body
            unneedkeys = ['name_mark', 'filters', 'url', 'template', 'target', 'channel']
            lark_body.update({key: dest[key] for key in dest if key not in unneedkeys})
            self.logging.debug(f"{dest_mark} body: {json.dumps(lark_body, ensure_ascii=False)}")
            lark_res = requests.post(lark_url, json=lark_body)
            formatted_res_text = self._format_http_response_text(lark_res)
            self.logging.debug(f"{dest_mark} response: {formatted_res_text}")
            if lark_res.status_code != 200:
                return False, f"{dest_mark} error: {formatted_res_text}"
            else:
                lark_res_json = lark_res.json()
                if lark_res_json.get('code') != 0:
                    return False, f"{dest_mark} error: {formatted_res_text}"
            return True, formatted_res_text
        except Exception as e:
            return False, f"{dest_mark} error: {e}"
    
    def notification(self, title, body):
        subprocess.run([
            'osascript', '-e', f'display notification "{body}" with title "{title}"'
        ], check=True)

    def save_to_clipboard(self, code):
        pyperclip.copy(str(code))


config = Config()


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