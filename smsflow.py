import os, sys, time, datetime, json, sqlite3, traceback, copy, random
import regex, typedstream

from base import config
from base import Base

message_db_file_path = os.path.expanduser('~/Library/Messages/chat.db')

CONFIG_DEFAULTS = {
    "forward": {
        "strategy": "all",
    },
    "alarm": {
        "strategy": "until_success",
    },
    "channel": {
        "webhook": {
            "logmarker": "🌐",
            "method": "POST",
        },
        "bark": {
            "logmarker": "📣",
            "method": "POST",
            "url": "https://api.day.app/push",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}\n{{source}} - {{receive_time}}",
                    "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                    "$alarm": "{{msg}}\n\n{{traceback}}"
                },
                "copy": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                    "$code": "{{code}}",
                    "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}"
                },
                "autoCopy": {
                    "$default": 0,
                    "$code": 1,
                    "$alarm": 0
                },
                "level": {
                    "$default": "active",
                    "$code": "timeSensitive",
                    "$alarm": "timeSensitive"
                },
            },
        },
        "pushgo": {
            "logmarker": "🌸",
            "method": "POST",
            "url": "https://gateway.pushgo.cn/message",
            "payload": {
                "title": {
                    "$default": "{{receiver}} <- {{sender}}",
                    "$code": "🌀 {{code}}",
                    "$alarm": "{{source}}: {{error}}",
                },
                "body": {
                    "$default": "{{text}}  \n{{source}} - {{receive_time}}",
                    "$code": "{{receiver}} <- {{sender}}  \n{{text}}  \n{{source}} - {{receive_time}}",
                    "$alarm": "{{msg}}  \n  \n{{traceback}}"
                },
            }
        },
        "tgbot": {
            "logmarker": "🤖",
            "method": "POST",
            "payload": {
                "text": {
                    "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                    "$code": "🌀 {{code}}\n{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                    "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}"
                },
                "parse_mode": "HTML",
                "link_preview_options": {
                    "is_disabled": True
                }
            },
        },
        "lark": {
            "logmarker": "📘",
            "method": "POST",
            "payload": {
                "$default": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"blue\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{receive_time}}\",\"tag\":\"lark_md\"}}]}}",
                "$code": "{\"header\":{\"template\":\"green\",\"title\":{\"content\":\"{{receiver}} <- {{sender}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"column_set\",\"flex_mode\":\"none\",\"background_style\":\"grey\",\"horizontal_spacing\":\"default\",\"columns\":[{\"tag\":\"column\",\"width\":\"weighted\",\"weight\":1,\"elements\":[{\"tag\":\"markdown\",\"text_align\":\"center\",\"content\":\"验证码\\n{{code}}\\n\"}]}]},{\"tag\":\"div\",\"text\":{\"content\":\"{{text}}\\n{{source}} - {{receive_time}}\",\"tag\":\"lark_md\"}}]}",
                "$alarm": "{\"msg_type\":\"interactive\",\"card\":{\"header\":{\"template\":\"red\",\"title\":{\"content\":\"{{source}}: {{error}}\",\"tag\":\"plain_text\"}},\"elements\":[{\"tag\":\"div\",\"text\":{\"content\":\"{{msg}}\\n\\n{{traceback}}\",\"tag\":\"lark_md\"}}]}}"
            },
            "success_json": {
                "code": 0,
            }
        },
        "notification": {
            "logmarker": "🔔",
            "title": {
                "$default": "{{receiver}} <- {{sender}}",
                "$code": "🌀 {{code}}",
                "$alarm": "{{source}}: {{error}}",
            },
            "body": {
                "$default": "{{text}}\n{{source}} - {{receive_time}}",
                "$code": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                "$alarm": "{{msg}}\n\n{{traceback}}"
            },
            "copy": {
                "$default": "{{receiver}} <- {{sender}}\n{{text}}\n{{source}} - {{receive_time}}",
                "$code": "{{code}}",
                "$alarm": "{{source}}: {{error}}\n\n{{msg}}\n\n{{traceback}}",
            },
            "autoCopy": {
                "$default": 0,
                "$code": 1,
                "$alarm": 0
            }
        }
    }
}

def _format_ts(ts):
    try:
        ts_int = int(float(ts))
        return datetime.datetime.fromtimestamp(ts_int).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''

def _parse_time_str(time_str):
    try:
        dt = datetime.datetime.strptime(str(time_str), '%Y-%m-%d %H:%M:%S')
        return int(dt.timestamp())
    except Exception:
        return None

def _deep_merge_dicts(low_priority, high_priority):
    if not isinstance(low_priority, dict):
        low_priority = {}
    if not isinstance(high_priority, dict):
        high_priority = {}
    merged = dict(low_priority)
    for key, value in high_priority.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged

def _render_template(template, mapping):
    if not template:
        return ''
    mapping = mapping or {}
    template_str = str(template)

    def _repl(m):
        key = str(m.group(1)).strip()
        value = mapping.get(key)
        return '' if value is None else str(value)

    rendered = regex.sub(r"\{\{(\w+)\}\}", _repl, template_str)
    rendered = rendered.rstrip()
    if rendered.strip() == '':
        rendered = ''
    return rendered

def _is_value_condition_dict(value):
    if not isinstance(value, dict) or not value:
        return False
    allowed = {"$default", "$code", "$alarm"}
    return all(k in allowed for k in value.keys())

def _select_value_by_condition(value_dict, has_code, is_alarm):
    if is_alarm and "$alarm" in value_dict:
        return value_dict["$alarm"]
    if has_code and "$code" in value_dict:
        return value_dict["$code"]
    if "$default" in value_dict:
        return value_dict["$default"]
    for _, v in value_dict.items():
        return v
    return None

def _try_parse_json(value):
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except Exception:
        return None

def _render_value(value, mapping, has_code, is_alarm, key_name=None):
    if _is_value_condition_dict(value):
        chosen = _select_value_by_condition(value, has_code=has_code, is_alarm=is_alarm)
        return _render_value(chosen, mapping, has_code=has_code, is_alarm=is_alarm, key_name=key_name)

    if isinstance(value, dict):
        rendered = {}
        for k, v in value.items():
            rendered[k] = _render_value(v, mapping, has_code=has_code, is_alarm=is_alarm, key_name=k)
        return rendered

    if isinstance(value, list):
        return [_render_value(v, mapping, has_code=has_code, is_alarm=is_alarm, key_name=key_name) for v in value]

    if isinstance(value, str):
        if key_name == "payload":
            parsed = _try_parse_json(value)
            if isinstance(parsed, (dict, list)):
                return _render_value(parsed, mapping, has_code=has_code, is_alarm=is_alarm, key_name=None)
        return _render_template(value, mapping)

    return value


class LiteDB(object):
    def __init__(self, db_file):
        self.db_file = db_file
    
    def dict_factory(self, cursor, row): 
        dict_c = {} 
        for idx, col in enumerate(cursor.description): 
            dict_c[col[0]] = row[idx] 
        return dict_c

    def conn(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = self.dict_factory
        cursor = conn.cursor()
        return conn, cursor
    
    def select(self, sql):
        conn, cursor = self.conn()
        result = list(cursor.execute(sql))
        conn.commit()
        conn.close()
        return result


class SMSFlow(Base):
    def __init__(self):
        super(SMSFlow, self).__init__()
        self.db = LiteDB(db_file=message_db_file_path)
        self.root_opt = config.user_config or {}
        self.channel_opt = self.root_opt.get('channel', {})
        self.target_opt = self.root_opt.get('target', {})
        self.fwd_opt = self.root_opt.get('forward', {})
        self.alarm_opt = self.root_opt.get('alarm', {})
        self.forward_destinations = self._build_forward_destinations()
        self.alarm_destinations = self._build_alarm_destinations()
        self.is_1st_start = True
        self.update_time = {}
        saved_update_time = None
        self.last_fwd_time_file = config.record_file_path
        if os.path.exists(self.last_fwd_time_file):
            with open(self.last_fwd_time_file, 'r') as fp:
                try:
                    saved_update_time = json.load(fp)
                except Exception as e:
                    print(f"Reading last_fwd_time_file with error: {e}")
        self.init_update_time(saved_update_time)

    def init_update_time(self, saved_update_time: dict):
        init_timestamp = int(time.time())
        for dest in self.forward_destinations:
            dest_name = dest['name_mark']
            if dest.get('channel') == 'notification':
                self.update_time[dest_name] = init_timestamp
                continue
            if saved_update_time and dest_name in saved_update_time:
                saved_value = saved_update_time[dest_name]
                parsed = _parse_time_str(saved_value)
                if parsed is None:
                    raise ValueError(
                        f"saved_update_time has invalid time format for '{dest_name}': {saved_value}"
                    )
                self.update_time[dest_name] = parsed
            else:
                self.update_time[dest_name] = init_timestamp
        self.min_update_time = min(self.update_time.values())
        self.last_new_msg_time = init_timestamp
    
    def mock2notify(self, count): 
        with open(os.path.expanduser(f"./sms/sms.json"), 'r') as f:
            msgs_list = json.load(f)
        if not isinstance(msgs_list, list):
            raise ValueError(f"invalid sms.json format, expected list, got {type(msgs_list)}")
        actual_count = min(len(msgs_list), count)
        new_msgs = random.sample(msgs_list, actual_count)
        self.init_update_time({})
        for idx, msg in enumerate(new_msgs):
            msg["timestamp"] = self.min_update_time + idx + 1
            msg["time_str"] = _format_ts(msg["timestamp"])
        
        try:
            self.check2notify(mock=True, mock_msgs=new_msgs)
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())

    def check_forward_destinations(self):
        if not self.forward_destinations:
            self.logging.error("❌ no forward destinations, stop check")
            sys.exit(1)
        for dest in self.forward_destinations:
            try:
                dest_name = dest.get("name_mark")
                dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
                check_msg = f"{dest_mark} check passed"
                rendered_dest = self._render_destination(dest, is_alarm=True, error=check_msg)
                cur_status, cur_res = self._send_to_destination(rendered_dest)
                if not cur_status:
                    self.logging.error(f"❌ {dest_mark} error: {cur_res}")
                    sys.exit(1)
            except Exception as e:
                self.logging.error(f"❌ {dest_mark} error: {e}")
                sys.exit(1)
    
    def _supported_forward_template_vars(self):
        return set(self._build_tmpl_mapping({}).keys())

    def _supported_alarm_template_vars(self):
        return self._supported_forward_template_vars() | {"error", "traceback"}
        
    def write_last_fwd_time_ro_file(self, mock: bool = False):
        self.is_1st_start = False
        if mock:
            return
        with open(self.last_fwd_time_file, 'w') as f:
            json.dump({k: _format_ts(v) for k, v in self.update_time.items()}, f, indent=4)
    
    def get_msg_from_applearchive(self, archived_object):
        msgs = []
        unarchived_object = typedstream.unarchive_from_data(archived_object)
        for content in unarchived_object.contents:
            for item in content.values:
                if isinstance(item, typedstream.types.foundation.NSMutableString) or isinstance(item, typedstream.types.foundation.NSString):
                    msgs.append(item.value)
        return '\n'.join(msgs)

    def query_new_messages(self):
        sql = """
        select
            message.rowid,
            ifnull(handle.uncanonicalized_id, chat.chat_identifier) AS sender,
            message.service,
            (message.date / 1000000000 + 978307200) AS timestamp,
            message.text,
            message.attributedBody,
            message.destination_caller_id AS receiver
        from
            message
                left join chat_message_join
                        on chat_message_join.message_id = message.ROWID
                left join chat
                        on chat.ROWID = chat_message_join.chat_id
                left join handle
                        on message.handle_id = handle.ROWID
        where
            is_from_me = 0
            and (message.date / 1000000000 + 978307200) > {min_update_time}
        order by
            message.date
        """
        data = self.db.select(sql.format(min_update_time=self.min_update_time))
        for row in data[:]:
            row['time_str'] = _format_ts(row.get('timestamp', 0))
            if not row.get('text'):
                if row.get('attributedBody'):
                    row['text'] = self.get_msg_from_applearchive(row.get('attributedBody'))
                else:
                    data.remove(row)
            row.pop('attributedBody', None)
        return data
    
    def is_filter_matched(self, msg, match, match_type):
        try:
            if match_type == 'and':
                return all(key in msg and regex.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'or':
                return any(key in msg and regex.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'selector':
                return all((bool(pattern) and bool(msg.get(key))) or ((not bool(pattern)) and (not msg.get(key))) for key, pattern in match.items())
        except Exception as e:
            self.logging.error(f"❌ filter error: {e}")
            return False
        
    def check_filters(self, msg, filters):
        if filters:
            for f in filters:
                if not self.is_filter_matched(msg, f['match'], f['type']):
                    self.logging.debug(f"🕸️  filter [x]: {json.dumps(f, ensure_ascii=False, default=str)}")
                    return False
                else:
                    self.logging.debug(f"🕸️  filter [√]: {json.dumps(f, ensure_ascii=False, default=str)}")
            return True
        else:
            self.logging.debug(f"🕸️ no filters")
            return True
    
    def _resolve_destination(self, destination):
        target_name = destination['target']
        target_cfg = self.target_opt[target_name]
        channel_name = target_cfg['channel']
        default_channel_cfg = CONFIG_DEFAULTS.get("channel", {}).get(channel_name, {})
        user_channel_cfg = self.channel_opt.get(channel_name) or {}

        merged = _deep_merge_dicts(default_channel_cfg, user_channel_cfg)
        merged = _deep_merge_dicts(merged, target_cfg)
        merged = _deep_merge_dicts(merged, destination)
        merged['name_mark'] = destination.get('name_mark') or target_name
        return merged

    def _build_destinations(self, destinations):
        built = []
        name_marks = set()
        for dest in destinations:
            payload = self._resolve_destination(dest)
            name_mark = payload['name_mark']
            if name_mark in name_marks:
                raise Exception(f"duplicate destination name_mark '{name_mark}'")
            name_marks.add(name_mark)
            built.append(payload)
        return built

    def _build_forward_destinations(self):
        destinations = self.fwd_opt.get('destinations') or []
        try:
            return self._build_destinations(destinations)
        except Exception as e:
            raise Exception(f"build_forward_destinations error: {e}")

    def _build_alarm_destinations(self):
        destinations = self.alarm_opt.get('destinations') or []
        try:
            return self._build_destinations(destinations)
        except Exception as e:
            raise Exception(f"build_alarm_destinations error: {e}")

    def _build_tmpl_mapping(self, msg, **kwargs):
        msg_str = json.dumps(msg, ensure_ascii=False, default=str) if msg else ''
        mapping = {
            "sender": msg.get('sender'),
            "receiver": msg.get('receiver'),
            "text": msg.get('text'),
            "code": msg.get('code'),
            "receive_time": msg.get('time_str'),
            "msg": msg_str,
            "source": self.fwd_opt.get('source'),
        }
        for key, value in kwargs.items():
            if key in mapping and mapping[key] is not None:
                continue
            mapping[key] = value
        return mapping
    
    def _render_destination(self, dest: dict, msg: dict = {}, is_alarm: bool = False, **kwargs):
        mapping = self._build_tmpl_mapping(msg, **kwargs)
        rendered_dest = copy.deepcopy(dest)
        rendered_dest["code"] = msg.get("code")
        has_code = bool(msg.get("code"))
        rendered_dest = _render_value(rendered_dest, mapping, has_code=has_code, is_alarm=is_alarm)
        return rendered_dest

    def _send_to_destination(self, dest):
        notify = self.channel_notifiers[dest["channel"]]
        return notify(dest)

    def send_alarm(self, msg: dict = {}, **kwargs) -> bool:
        if not self.alarm_destinations:
            return False
        print("")
        self.logging.info(f"{'>' * 15} ⚠️ alarm start {'<' * 15}")
        try:
            strategy = self.alarm_opt.get('strategy') or CONFIG_DEFAULTS["alarm"]["strategy"]

            any_success = False
            any_failed = False
            for dest in self.alarm_destinations:
                rendered_dest = self._render_destination(dest, msg, True, **kwargs)
                cur_status, cur_res = self._send_to_destination(rendered_dest)
                if cur_status:
                    any_success = True
                    if strategy == 'until_success':
                        return True
                else:
                    any_failed = True
                    self.logging.error(f"❌ alarm failed: {cur_res}")
            if strategy == 'all':
                return not any_failed
            return any_success
        finally:
            self.logging.info(f"{'>' * 15} ⚠️ alarm end {'<' * 15}")

    def forward_message(self, msg):
        strategy = self.fwd_opt.get('strategy') or CONFIG_DEFAULTS["forward"]["strategy"]

        attempted = 0
        any_success = False
        any_failed = False
        errors = []
        for idx, dest in enumerate(self.forward_destinations):
            dest_name = dest['name_mark']
            dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
            msg_ts = msg.get('timestamp')
            last_ts = self.update_time.get(dest_name, 0)
            ts_passed = msg_ts > last_ts
            self.logging.debug(
                f"{dest_mark} ts "
                f"{'[√]' if ts_passed else '[x]'}: "
                f"{_format_ts(msg_ts)} {'>' if ts_passed else '<='} {_format_ts(last_ts)}"
                f" ({msg_ts} {'>' if ts_passed else '<='} {last_ts})"
            )
            if not ts_passed:
                continue
            if not self.check_filters(msg, dest.get('filters')):
                self.update_time[dest_name] = msg.get('timestamp')
                continue

            rendered_dest = self._render_destination(dest, msg, False)
            cur_status, cur_res = self._send_to_destination(rendered_dest)

            attempted += 1
            if cur_status:
                any_success = True
                self.update_time[dest_name] = msg.get('timestamp')
                if strategy == 'until_success':
                    for remaining in self.forward_destinations[idx + 1:]:
                        r_name = remaining['name_mark']
                        if msg.get('timestamp') > self.update_time.get(r_name, 0):
                            self.update_time[r_name] = msg.get('timestamp')
                    return True
            else:
                any_failed = True
                self.logging.error(f"❌ forward failed: {cur_res}")
                errors.append(f"{dest_name}: {cur_res}")

        if strategy == 'all':
            if attempted == 0:
                return True
            if any_failed:
                self.send_alarm(
                    msg,
                    error="some forward destinations failed under all strategy",
                    traceback="\n\n".join(errors) if errors else None,
                )
                return False
            return True

        if attempted == 0:
            return True
        if attempted > 0 and not any_success:
            self.send_alarm(
                msg,
                error="all destinations failed under until_success strategy",
                traceback="\n\n".join(errors) if errors else None,
            )
        return any_success
    
    def check2notify(self, mock: bool = False, mock_msgs: list = []):
        self.min_update_time = min(self.update_time.values())
        self.logging.debug(f"update_time: { {k: f'{_format_ts(v)}({v})' for k, v in self.update_time.items()} }")
        self.logging.debug(f"min_update_time: {_format_ts(self.min_update_time)}({self.min_update_time})")
        c_timestamp = int(time.time())
        
        if mock:
            new_msgs = mock_msgs
        else:
            new_msgs = self.query_new_messages()
        
        if new_msgs:
            self.last_new_msg_time = c_timestamp
            self.logging.info(json.dumps(new_msgs, ensure_ascii=False))
            for msg in new_msgs:
                try:
                    print("")
                    self.logging.info(f"{'>' * 15} 📩 new message {'<' * 15}")
                    # get code from message
                    msg['code'] = self.get_code_from_text(msg.get('text'))
                    self.logging.info(f"✉️  message: {json.dumps(msg, ensure_ascii=False)}")
                    # forward messagge
                    self.forward_message(msg)
                except Exception as e:
                    traceback.print_exc()
                    self.send_alarm(msg=msg, error=str(e), traceback=traceback.format_exc())
                    continue
                finally:
                    self.logging.info(f"{'>' * 15} 📩 processed {'<' * 15}")

            # write forward time to file after all messages processed
            self.write_last_fwd_time_ro_file(mock)
            
        # write forward time to file only when no message received for 10 minutes   
        elif c_timestamp - self.min_update_time > 60 * 10:
            self.update_time = {key: c_timestamp for key in self.update_time}
            self.write_last_fwd_time_ro_file(mock)
            
        # write forward time to file when first start to avoid long time waiting
        elif self.is_1st_start:
            self.write_last_fwd_time_ro_file(mock)

        # notify when no message received for every 24 hours
        if c_timestamp - self.last_new_msg_time > 60 * 60 * 24:
            self.notification("No message received for 24h", "")
            self.send_alarm(error="no message received for 24h")
            self.last_new_msg_time = c_timestamp
    
    def update_hook(self):
        try:
            self.check2notify()
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())