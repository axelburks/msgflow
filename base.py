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

    def _match_success_json(self, expected, actual):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for k, v in expected.items():
                if k not in actual:
                    return False
                if not self._match_success_json(v, actual[k]):
                    return False
            return True
        if isinstance(expected, list):
            if not isinstance(actual, list):
                return False
            if len(expected) != len(actual):
                return False
            return all(self._match_success_json(e, a) for e, a in zip(expected, actual))
        return expected == actual
        
    def get_code_from_text(self, text):
        code = None
        if not text:
            return None
        
        pattern_flags = r"(?<!回复|回覆|获取|獲取)((验证|驗證|授权|授權|校验|校驗|检验|檢驗|确认|確認|激活|动态|動態|安全|登入|认证|認證|识别|識別|交易|短信|随机|隨機|一次性)(代?码|代?碼|口令|密码|密碼|编码|編碼|序号|序號)|([Vv]erification|[Vv]alidation|[Ss]ecurity)? ?[Cc]ode)"
        
        pattern_captchas = r"(?<!(联系|聯繫|致电我行|致電我行|结尾|結尾|尾号码?|尾號碼?|尾4位|ending |[A-Za-z0-9]))([0-9][0-9-]{3,7})(?![A-Za-z0-9]|\]?(-| -)|服务热线|服務熱線)"

        text_escaped = regex.sub(r'((https?|ftp|file):\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|$!:,.;]*[A-Z0-9+&@#\/%=~_|$]|\n', ' ', text, flags=regex.I)

        match_flags = regex.search(pattern_flags, text_escaped, flags=regex.I)
        matches_captchas = regex.findall(pattern_captchas, text_escaped)
        
        if match_flags and matches_captchas:
            max_distance = 80
            flag_index = text_escaped.find(match_flags.group())
            closest_captcha = min(matches_captchas, key=lambda x: abs(text_escaped.find(x[1]) - flag_index))[1]
            if abs(text_escaped.find(closest_captcha) - flag_index) <= max_distance:
                code = closest_captcha
        
        return code

    @channel('webhook')
    def notify_to_webhook(self, dest):
        logmarker = dest.get('logmarker')
        dest_mark = f"{logmarker} {dest.get('name_mark')}({dest.get('channel')})"
        try:
            self.logging.info(f"{dest_mark}")
            method = dest.get('method').upper()
            url = dest.get('url')
            params = dest.get('params')
            headers = dest.get('headers')
            payload = dest.get('payload')
            timeout = dest.get('timeout')
            req_kwargs = {}
            if params is not None:
                req_kwargs["params"] = params
            if headers is not None:
                req_kwargs["headers"] = headers
            if payload is not None:
                req_kwargs["json"] = payload
            if timeout is not None:
                req_kwargs["timeout"] = timeout

            self.logging.debug(f"{dest_mark} request: {method} {url} {json.dumps(req_kwargs, ensure_ascii=False, default=str)}")
            res = requests.request(method, url, **req_kwargs)
            formatted_res_text = self._format_http_response_text(res)
            self.logging.debug(f"{dest_mark} response: {res.status_code} {formatted_res_text}")

            success_json = dest.get('success_json')
            if success_json is None:
                if res.status_code != 200:
                    return False, f"{dest_mark} error: {formatted_res_text}"
                return True, formatted_res_text
            try:
                res_json = res.json()
            except Exception:
                return False, f"{dest_mark} error: invalid json response: {formatted_res_text}"
            if not self._match_success_json(success_json, res_json):
                return False, f"{dest_mark} error: {formatted_res_text}"
            return True, formatted_res_text
        except Exception as e:
            return False, f"{dest_mark} error: {e}"

    @channel('bark')
    def notify_to_bark(self, dest):
        return self.notify_to_webhook(dest)
        
    @channel('pushgo')
    def notify_to_pushgo(self, dest):
        return self.notify_to_webhook(dest)
        
    @channel('tgbot')
    def notify_to_tgbot(self, dest):
        try:
            payload = dest.get('payload')
            if (
                isinstance(payload, dict)
                and 'text' in payload
                and str(payload.get('parse_mode') or '').upper() == 'HTML'
            ):
                escaped_text = html.escape(payload.get('text'))
                code = dest.get('code')
                if code:
                    escaped_text = escaped_text.replace(code, f"<code>{code}</code>")
                payload['text'] = escaped_text
                dest['payload'] = payload
            return self.notify_to_webhook(dest)
        except Exception as e:
            logmarker = dest.get('logmarker')
            dest_mark = f"{logmarker} {dest.get('name_mark')}({dest.get('channel')})"
            return False, f"{dest_mark} error: {e}"

    @channel('lark')
    def notify_to_lark(self, dest):
        return self.notify_to_webhook(dest)
    
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
            msgs_list = json.load(f)
        test = Base()
        for msg in msgs_list:
            code = test.get_code_from_text(msg['text'])
            if code != msg.get('code_expected'):
                print(f"text: {msg['text']}\nexpected: {msg.get('code_expected')}, got: {code}\n")
    except FileNotFoundError:
        print("msg_file not found.")