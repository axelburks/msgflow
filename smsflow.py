import os, time, datetime, json, sqlite3, traceback
import regex, typedstream

from base import config
from base import Base

message_db_file_path = os.path.expanduser('~/Library/Messages/chat.db')

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
    rendered = str(template)
    for key, value in mapping.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", '' if value is None else str(value))
    return rendered

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
        self.channel_opt = self.root_opt.get('channel', {}) or {}
        self.target_opt = self.root_opt.get('target', {}) or {}
        self.fwd_opt = self.root_opt.get('forward', {}) or {}
        self.alarm_opt = self.root_opt.get('alarm', {}) or {}
        self.fwd_default_tpl = {
            "title": "{{receiver}} <- {{sender}}",
            "body": "{{text}}\n{{source}} - {{receive_time}}",
            "title_code": "🌀 {{code}}"
        }
        self.alarm_default_tpl = {
            "title": "{{source}}: {{error}}",
            "body": "msg={{msg}}\ntraceback={{traceback}}"
        }
        self.forward_destinations = self._build_forward_destinations()
        self.alarm_destinations = self._build_alarm_destinations()
        self.is_1st_start = True
        init_timestamp = int(time.time())
        saved_update_time = None
        self.update_time = {}
        self.last_fwd_time_file = config.record_file_path
        if os.path.exists(self.last_fwd_time_file):
            with open(self.last_fwd_time_file, 'r') as fp:
                try:
                    saved_update_time = json.load(fp)
                except Exception as e:
                    print(f"Reading last_fwd_time_file with error: {e}")
        for dest in self.forward_destinations:
            dest_name = dest['name_mark']
            if saved_update_time and dest_name in saved_update_time:
                saved_value = saved_update_time[dest_name]
                parsed = _parse_time_str(saved_value)
                if parsed is None:
                    raise ValueError(
                        f"{self.last_fwd_time_file} has invalid time format for '{dest_name}': {saved_value}"
                    )
                self.update_time[dest_name] = parsed
            else:
                self.update_time[dest_name] = init_timestamp
        self.update_time['notify_time'] = init_timestamp
        self.min_update_time = min(self.update_time.values())
        self.last_new_msg_time = init_timestamp
        
    def write_last_fwd_time_ro_file(self):
        self.is_1st_start = False
        with open(self.last_fwd_time_file, 'w') as f:
            json.dump({k: _format_ts(v) for k, v in self.update_time.items()}, f, indent=4)
    
    def get_msg_from_applearchive(self, archived_object):
        msgs = []
        unarchived_object = typedstream.unarchive_from_data(archived_object)
        for content in unarchived_object.contents:
            for item in content.values:
                if isinstance(item, typedstream.types.foundation.NSMutableString):
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
                    row['attributedBody'] = ''
                else:
                    data.remove(row)
            else:
                row['attributedBody'] = ''
        return data
    
    def is_filter_matched(self, msg, match, match_type):
        try:
            if match_type == 'and':
                return all(key in msg and regex.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'or':
                return any(key in msg and regex.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'selector':
                return all((pattern == 'have' and msg.get(key)) or (pattern == 'none' and not msg.get(key)) for key, pattern in match.items())
        except regex.error as e:
            self.logging.error(f"Regex error: {e}")
            return False
        
    def check_filters(self, msg, filters):
        if filters:
            return all(self.is_filter_matched(msg, f['match'], f['type']) for f in filters)
        else:
            return True
    
    def _resolve_destination(self, destination):
        target_name = destination['target']
        if target_name not in self.target_opt:
            raise Exception(f"target '{target_name}' not found in config.target")
        target_cfg = self.target_opt[target_name]
        channel_name = target_cfg['channel']
        if channel_name not in self.channel_opt:
            raise Exception(f"channel '{channel_name}' not found in config.channel")
        channel_cfg = self.channel_opt[channel_name]
        merged = _deep_merge_dicts(channel_cfg, target_cfg)
        merged = _deep_merge_dicts(merged, destination)
        name_mark = destination.get('name_mark') or target_name
        merged['name_mark'] = name_mark
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

    def _send_to_destination(self, payload, title, body, code=None):
        channel_name = payload.get('channel')
        dest_name = payload.get('name_mark')
        if channel_name == 'bark':
            return self.notify_to_bark(payload, title, body, code=code)
        elif channel_name == 'pushgo':
            return self.notify_to_pushgo(payload, title, body, code=code)
        elif channel_name == 'tgbot':
            return self.notify_to_tgbot(payload, title, body, code=code)
        elif channel_name == 'lark':
            return self.notify_to_lark(payload, title, body, code=code)
        return False, f"❓ {dest_name}({channel_name}) error: unsupported channel"

    def _build_tmpl_mapping(self, msg, **kwargs):
        mapping = {
            "sender": msg.get('sender'),
            "receiver": msg.get('receiver'),
            "text": msg.get('text'),
            "code": msg.get('code'),
            "receive_time": msg.get('time_str'),
            "msg": json.dumps(msg, ensure_ascii=False, default=str),
            "source": self.fwd_opt.get('source'),
        }
        for key, value in kwargs.items():
            if key in mapping:
                continue
            mapping[key] = value

        return mapping
    
    def gen_alarm_msg(self, msg, alarm_template, **kwargs):
        mapping = self._build_tmpl_mapping(msg, **kwargs)
        title = _render_template(alarm_template.get('title'), mapping)
        body = _render_template(alarm_template.get('body'), mapping)
        return title, body

    def send_alarm(self, msg: dict = {}, **kwargs) -> bool:
        if not self.alarm_destinations:
            return False
        self.logging.info(f"{"#" * 15} ⚠️ alarm starting {"#" * 15}")
        try:
            strategy = (self.alarm_opt.get('strategy') or 'all').strip()
            merged_base_template = _deep_merge_dicts(self.alarm_default_tpl, self.alarm_opt.get('template', {}) or {})

            any_success = False
            any_failed = False
            for dest in self.alarm_destinations:
                merged_template = _deep_merge_dicts(merged_base_template, dest.get('template', {}) or {})
                title, body = self.gen_alarm_msg(msg, merged_template, **kwargs)
                cur_status, cur_res = self._send_to_destination(dest, title, body, code=msg.get('code'))
                if cur_status:
                    any_success = True
                    if strategy == 'until_success':
                        return True
                else:
                    any_failed = True
                    self.logging.error(f"alarm({dest.get('name_mark') or dest.get('channel')}): {cur_res}")
            if strategy == 'all':
                return not any_failed
            return any_success
        finally:
            self.logging.info(f"{"#" * 15} ⚠️ alarm finished {"#" * 15}")

    def gen_fwd_msg(self, msg, msg_template, **kwargs):
        mapping = self._build_tmpl_mapping(msg, **kwargs)
        fwd_msg_title = _render_template(msg_template.get('title'), mapping)
        fwd_msg_body = _render_template(msg_template.get('body'), mapping)
        fwd_msg_title_code = _render_template(msg_template.get('title_code'), mapping) if msg_template.get('title_code') and msg.get('code') else ''
        if fwd_msg_title_code:
            fwd_msg_body = f"{fwd_msg_title}\n{fwd_msg_body}"
            fwd_msg_title = fwd_msg_title_code
        return fwd_msg_title, fwd_msg_body

    def forward_message(self, msg):
        strategy = (self.fwd_opt.get('strategy') or 'all').strip()
        merged_base_template = _deep_merge_dicts(self.fwd_default_tpl, self.fwd_opt.get('template', {}) or {})

        attempted = 0
        any_success = False
        any_failed = False
        errors = []
        for idx, dest in enumerate(self.forward_destinations):
            dest_name = dest['name_mark']
            if msg.get('timestamp') <= self.update_time.get(dest_name, 0):
                continue
            if not self.check_filters(msg, dest.get('filters')):
                self.update_time[dest_name] = msg.get('timestamp')
                continue

            merged_template = _deep_merge_dicts(merged_base_template, dest.get('template', {}) or {})
            fwd_msg_title, fwd_msg_body = self.gen_fwd_msg(msg, merged_template)
            cur_status, cur_res = self._send_to_destination(dest, fwd_msg_title, fwd_msg_body, code=msg.get('code'))

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
                    traceback="\n".join(errors) if errors else None,
                )
                return False
            return True

        if attempted == 0:
            return True
        if attempted > 0 and not any_success:
            self.send_alarm(
                msg,
                error="all destinations failed under until_success strategy",
                traceback="\n".join(errors) if errors else None,
            )
        return any_success
    
    def _check2notify(self):
        self.logging.debug('checking')
        self.min_update_time = min(self.update_time.values())
        self.logging.debug(
            f"update_time: { {k: f"{_format_ts(v)}({v})" for k, v in self.update_time.items()} }"
        )
        self.logging.debug(f"min_update_time: {_format_ts(self.min_update_time)}({self.min_update_time})")
        c_timestamp = int(time.time())
        
        new_msgs = self.query_new_messages()
        if new_msgs:
            self.last_new_msg_time = c_timestamp
            self.logging.info(json.dumps(new_msgs, ensure_ascii=False, indent=2))
            for msg in new_msgs:
                try:
                    # get code from message
                    msg['code'] = self.get_code_from_msg(msg.get('text'))
                    # notify message
                    if msg['timestamp'] > self.update_time['notify_time']:
                        self.update_time['notify_time'] = msg['timestamp']
                        if msg.get('code'):
                            self.notification(msg['code'], msg['text'])
                            self.save_to_clipboard(msg['code'])
                    # forward messagge
                    self.forward_message(msg)
                except Exception as e:
                    traceback.print_exc()
                    self.send_alarm(msg=msg, error=str(e), traceback=traceback.format_exc())
                    continue

            # write forward time to file after all messages processed
            self.write_last_fwd_time_ro_file()
            
        # write forward time to file only when no message received for 10 minutes   
        elif c_timestamp - self.min_update_time > 60 * 10:
            self.update_time = {key: c_timestamp for key in self.update_time}
            self.write_last_fwd_time_ro_file()
            
        # write forward time to file when first start to avoid long time waiting
        elif self.is_1st_start:
            self.write_last_fwd_time_ro_file()

        # notify when no message received for every 24 hours
        if c_timestamp - self.last_new_msg_time > 60 * 60 * 24:
            self.notification("No message received for 24h", "")
            self.send_alarm(error="no message received for 24h", traceback="{}")
            self.last_new_msg_time = c_timestamp
    
    def update_hook(self):
        try:
            self._check2notify()
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())