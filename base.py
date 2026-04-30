import os, logging, json, html, subprocess, copy
from typing import Optional
import requests, regex, pyperclip

TPL_VAR_PATTERN = r"\{\{(\w+)\}\}"

def deep_merge_dicts(low_priority, high_priority):
    if not isinstance(low_priority, dict):
        low_priority = {}
    if not isinstance(high_priority, dict):
        high_priority = {}
    merged = dict(low_priority)
    for key, value in high_priority.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged

def render_template(template, mapping):
    if not template:
        return ''
    mapping = mapping or {}
    template_str = str(template)

    def _repl(m):
        key = str(m.group(1)).strip()
        value = mapping.get(key)
        return '' if value is None else str(value)

    rendered = regex.sub(TPL_VAR_PATTERN, _repl, template_str)
    rendered = rendered.strip()
    return rendered

def build_tpl_mapping(msg: dict, **kwargs):
    mapping = {
        "sender": msg.get('sender'),
        "receiver": msg.get('receiver'),
        "text": msg.get('text'),
        "timestamp": msg.get('timestamp'),
        "time_str": msg.get('time_str'),
        "msg": msg.get('msg'),
        "code": msg.get('code'),
        "source": msg.get('source'),
        "error": kwargs.get('error'),
        "traceback": kwargs.get('traceback'),
    }
    for key, value in kwargs.items():
        if key in mapping and mapping[key] is not None:
            continue
        mapping[key] = value
    return mapping

def collect_tpl_vars(value, key_name: Optional[str] = None):
    if is_value_condition_dict(value):
        used = set()
        for v in value.values():
            used |= collect_tpl_vars(v, key_name=key_name)
        return used

    if isinstance(value, dict):
        used = set()
        for k, v in value.items():
            used |= collect_tpl_vars(v, key_name=str(k))
        return used

    if isinstance(value, list):
        used = set()
        for v in value:
            used |= collect_tpl_vars(v, key_name=key_name)
        return used

    if isinstance(value, str):
        used = set(regex.findall(TPL_VAR_PATTERN, value))
        if key_name == "payload":
            parsed = try_parse_json(value)
            if isinstance(parsed, (dict, list)):
                used |= collect_tpl_vars(parsed, key_name=None)
        return used

    return set()

def is_value_condition_dict(value):
    if not isinstance(value, dict) or not value:
        return False
    return all(k in ALLOWED_COND_KEYS for k in value.keys())

def select_value_by_condition(value_dict, has_code, is_alarm):
    if is_alarm and "$alarm" in value_dict:
        return value_dict["$alarm"]
    if has_code and "$code" in value_dict:
        return value_dict["$code"]
    if "$default" in value_dict:
        return value_dict["$default"]
    for _, v in value_dict.items():
        return v
    return None

def try_parse_json(value):
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except Exception:
        return None

def render_value(value, mapping, has_code, is_alarm, key_name=None):
    if is_value_condition_dict(value):
        chosen = select_value_by_condition(value, has_code=has_code, is_alarm=is_alarm)
        return render_value(chosen, mapping, has_code=has_code, is_alarm=is_alarm, key_name=key_name)

    if isinstance(value, dict):
        rendered = {}
        for k, v in value.items():
            rendered[k] = render_value(v, mapping, has_code=has_code, is_alarm=is_alarm, key_name=k)
        return rendered

    if isinstance(value, list):
        return [render_value(v, mapping, has_code=has_code, is_alarm=is_alarm, key_name=key_name) for v in value]

    if isinstance(value, str):
        if key_name == "payload":
            parsed = try_parse_json(value)
            if isinstance(parsed, (dict, list)):
                return render_value(parsed, mapping, has_code=has_code, is_alarm=is_alarm, key_name=None)
        return render_template(value, mapping)

    return value

def render_destination(dest: dict, msg: dict = {}, is_alarm: bool = False, **kwargs):
    mapping = build_tpl_mapping(msg, **kwargs)
    rendered_dest = copy.deepcopy(dest)
    rendered_dest["code"] = msg.get('code')
    has_code = bool(msg.get('code'))
    rendered_dest = render_value(rendered_dest, mapping, has_code=has_code, is_alarm=is_alarm)
    return rendered_dest

def build_channel_notifiers_for_cls(cls):
    channel_notifiers = {}
    for attr in dir(cls):
        fn = getattr(cls, attr, None)
        if not callable(fn):
            continue
        channel_name = getattr(fn, "_msgflow_channel", None)
        if not channel_name:
            continue
        if channel_name in channel_notifiers:
            raise Exception(f"duplicate channel notifier for '{channel_name}'")
        channel_notifiers[channel_name] = fn
    return channel_notifiers

def channel(name: str):
    def decorator(fn):
        fn._msgflow_channel = name
        return fn
    return decorator

class Base(object):

    def __init__(self):
        self.logging = logging.getLogger(__name__)
    
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
    
    @channel('notification')
    def notification(self, dest):
        logmarker = dest.get('logmarker')
        dest_mark = f"{logmarker} {dest.get('name_mark')}({dest.get('channel')})"
        self.logging.info(f"{dest_mark}")
        payload = dest.get('payload') or {}
        title = payload.get('title')
        body = payload.get('body')
        if not title or not body:
            return False, f"{dest_mark} error: title or body is empty in payload"
        try:
            result = subprocess.run(
                [
                    'osascript',
                    '-e',
                    f'display notification "{body}" with title "{title}"'
                ],
                check=True,
                capture_output=True,
                text=True
            )
            if payload.get('autoCopy') == 1 and payload.get('copy'):
                self.save_to_clipboard(payload.get('copy'))
            return True, result.stdout
        except Exception as e:
            return False, f"{dest_mark} error: {e}"

    def save_to_clipboard(self, code):
        pyperclip.copy(str(code))

CHANNEL_NOTIFIERS = build_channel_notifiers_for_cls(Base)
AVAILABLE_CHANNELS = tuple(CHANNEL_NOTIFIERS.keys())
LOCAL_CHANNELS = ("notification",)
REQ_CHANNELS = tuple(c for c in AVAILABLE_CHANNELS if c not in LOCAL_CHANNELS)
ALLOWED_MATCH_TPL_VARS = tuple(build_tpl_mapping({}).keys())
ALLOWED_COND_KEYS = ("$default", "$code", "$alarm")

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