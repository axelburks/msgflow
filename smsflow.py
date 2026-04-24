import os, time, datetime, json, sqlite3, traceback
import regex, typedstream

from base import config
from base import Base

message_db_file_path = os.path.expanduser('~/Library/Messages/chat.db')

CONFIG_DEFAULTS = {
    "forward": {
        "strategy": "all",
        "template": {
            "title": "{{receiver}} <- {{sender}}",
            "body": "{{text}}\n{{source}} - {{receive_time}}",
            "title_code": "🌀 {{code}}",
        },
    },
    "alarm": {
        "strategy": "until_success",
        "template": {
            "title": "{{source}}: {{error}}",
            "body": "{{msg}}\n\n{{traceback}}",
        },
    },
}

CONFIG_SUPPORTED = {
    "strategies": {"all", "until_success"},
    "filters": {
        "types": {"and", "or", "selector"},
        "selector_values": {"have", "none"},
        "match_keys": {
            "rowid",
            "sender",
            "receiver",
            "service",
            "timestamp",
            "time_str",
            "text",
            "attributedBody",
            "code",
        },
    },
    "templates": {
        "forward_keys": {"title", "body", "title_code"},
        "alarm_keys": {"title", "body"},
    },
    "channels": {
        "bark": {"required_keys": {"url"}},
        "pushgo": {"required_keys": {"url"}},
        "tgbot": {"required_keys": {"url", "chat_id"}},
        "lark": {"required_keys": {"url"}},
    },
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
    rendered = str(template)
    for key, value in mapping.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", '' if value is None else str(value))
    return rendered

def _extract_template_vars(template):
    if template is None:
        return set()
    template_var_pattern = regex.compile(r"\{\{(\w+)\}\}")
    return set(template_var_pattern.findall(str(template)))

def _ensure_dict(value, path):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be a dict, got {type(value).__name__}")
    return value

def _ensure_list(value, path):
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{path} must be a list, got {type(value).__name__}")
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
        self._validate_user_config()
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
        
    def _validate_user_config(self):
        self.root_opt = _ensure_dict(self.root_opt, "config")
        self.channel_opt = _ensure_dict(self.channel_opt, "config.channel")
        self.target_opt = _ensure_dict(self.target_opt, "config.target")
        self.fwd_opt = _ensure_dict(self.fwd_opt, "config.forward")
        self.alarm_opt = _ensure_dict(self.alarm_opt, "config.alarm")

        self._validate_channels_config()
        self._validate_targets_config()
        self._validate_forward_config()
        self._validate_alarm_config()

    def _validate_strategy(self, value, path, default_value):
        normalized = (value or default_value).strip()
        supported = CONFIG_SUPPORTED["strategies"]
        if normalized not in supported:
            raise ValueError(f"{path} has unsupported value '{normalized}'; supported: {supported}")
        return normalized

    def _validate_template_obj(self, template_obj, *, allowed_keys, allowed_vars, path):
        template_obj = _ensure_dict(template_obj, path)
        unknown_keys = [k for k in template_obj.keys() if k not in allowed_keys]
        if unknown_keys:
            raise ValueError(f"{path} has unsupported keys: {unknown_keys}; supported: {allowed_keys}")
        for k, v in template_obj.items():
            used = _extract_template_vars(v)
            unknown_vars = [name for name in used if name not in allowed_vars]
            if unknown_vars:
                raise ValueError(f"{path}.{k} uses unsupported template vars: {unknown_vars}; supported: {allowed_vars}")

    def _supported_forward_template_vars(self):
        return set(self._build_tmpl_mapping({}).keys())

    def _supported_alarm_template_vars(self):
        return self._supported_forward_template_vars() | {"error", "traceback"}

    def _validate_filters(self, filters, path):
        filters = _ensure_list(filters, path)
        for i, f in enumerate(filters):
            f_path = f"{path}[{i}]"
            if not isinstance(f, dict):
                raise TypeError(f"{f_path} must be a dict, got {type(f).__name__}")
            t = f.get("type")
            if not isinstance(t, str) or not t.strip():
                raise ValueError(f"{f_path}.type must be a non-empty string")
            t = t.strip()
            supported_types = CONFIG_SUPPORTED["filters"]["types"]
            if t not in supported_types:
                raise ValueError(f"{f_path}.type has unsupported value '{t}'; supported: {supported_types}")
            match = f.get("match")
            match = _ensure_dict(match, f"{f_path}.match")
            if not match:
                raise ValueError(f"{f_path}.match must not be empty")
            supported_match_keys = CONFIG_SUPPORTED["filters"]["match_keys"]
            unknown_match_keys = [k for k in match.keys() if k not in supported_match_keys]
            if unknown_match_keys:
                raise ValueError(
                    f"{f_path}.match has unsupported keys: {unknown_match_keys}; supported: {supported_match_keys}"
                )
            if t == "selector":
                supported_selector_values = CONFIG_SUPPORTED["filters"]["selector_values"]
                for mk, mv in match.items():
                    mv_str = str(mv).strip()
                    if mv_str not in supported_selector_values:
                        raise ValueError(
                            f"{f_path}.match.{mk} has unsupported selector value '{mv_str}'; supported: {supported_selector_values}"
                        )
            else:
                for mk, mv in match.items():
                    try:
                        regex.compile(str(mv))
                    except regex.error as e:
                        raise ValueError(f"{f_path}.match.{mk} has invalid regex pattern: {e}")

    def _validate_channels_config(self):
        supported_channels = set(self.channel_notifiers.keys())
        unsupported_channel_cfg = [name for name in self.channel_opt.keys() if name not in supported_channels]
        if unsupported_channel_cfg:
            raise Exception(
                f"config.channel has unsupported channels: {unsupported_channel_cfg}; supported: {supported_channels}"
            )
        for channel_name, channel_cfg in self.channel_opt.items():
            if not isinstance(channel_cfg, dict):
                raise TypeError(f"config.channel.{channel_name} must be a dict, got {type(channel_cfg).__name__}")

    def _validate_targets_config(self):
        supported_channels = set(self.channel_notifiers.keys())
        for target_name, target_cfg in self.target_opt.items():
            if not isinstance(target_cfg, dict):
                raise TypeError(f"config.target.{target_name} must be a dict, got {type(target_cfg).__name__}")
            channel_name = target_cfg.get("channel")
            if not isinstance(channel_name, str) or not channel_name.strip():
                raise Exception(f"target '{target_name}' missing required field: channel")
            channel_name = channel_name.strip()
            target_cfg["channel"] = channel_name
            if channel_name not in supported_channels:
                raise Exception(
                    f"target '{target_name}' refers to unsupported channel '{channel_name}'; supported: {supported_channels}"
                )

    def _validate_destination_payload(self, payload, path):
        channel_name = payload.get("channel")
        if not isinstance(channel_name, str) or not channel_name.strip():
            raise ValueError(f"{path} resolved payload missing channel")
        channel_name = channel_name.strip()
        if channel_name not in self.channel_notifiers:
            raise ValueError(f"{path} resolved payload has unsupported channel '{channel_name}'")
        requirements = CONFIG_SUPPORTED["channels"].get(channel_name, {})
        required_keys = requirements.get("required_keys") or set()
        missing = [k for k in required_keys if not payload.get(k)]
        if missing:
            raise ValueError(f"{path} resolved payload missing required keys for channel '{channel_name}': {missing}")

    def _validate_destinations(self, destinations, *, path, template_allowed_keys, template_allowed_vars):
        destinations = _ensure_list(destinations, path)
        name_marks = set()
        for i, dest in enumerate(destinations):
            d_path = f"{path}[{i}]"
            if not isinstance(dest, dict):
                raise TypeError(f"{d_path} must be a dict, got {type(dest).__name__}")
            target_name = dest.get("target")
            if not isinstance(target_name, str) or not target_name.strip():
                raise ValueError(f"{d_path}.target must be a non-empty string")
            if target_name not in self.target_opt:
                raise ValueError(f"{d_path}.target '{target_name}' not found in config.target")

            name_mark = dest.get("name_mark") or target_name
            if name_mark in name_marks:
                raise ValueError(f"{path} has duplicate destination name_mark '{name_mark}'")
            name_marks.add(name_mark)

            if "filters" in dest:
                self._validate_filters(dest.get("filters"), f"{d_path}.filters")
            if "template" in dest:
                dest["template"] = _ensure_dict(dest.get("template"), f"{d_path}.template")
                self._validate_template_obj(
                    dest["template"],
                    allowed_keys=template_allowed_keys,
                    allowed_vars=template_allowed_vars,
                    path=f"{d_path}.template",
                )
            payload = self._resolve_destination(dest)
            self._validate_destination_payload(payload, d_path)

    def _validate_forward_config(self):
        self.fwd_opt["strategy"] = self._validate_strategy(
            self.fwd_opt.get("strategy"),
            "config.forward.strategy",
            CONFIG_DEFAULTS["forward"]["strategy"],
        )
        base_vars = self._supported_forward_template_vars()
        template_keys = CONFIG_SUPPORTED["templates"]["forward_keys"]
        self.fwd_opt["template"] = _ensure_dict(self.fwd_opt.get("template"), "config.forward.template")
        self._validate_template_obj(
            self.fwd_opt["template"],
            allowed_keys=template_keys,
            allowed_vars=base_vars,
            path="config.forward.template",
        )
        self._validate_destinations(
            self.fwd_opt.get("destinations"),
            path="config.forward.destinations",
            template_allowed_keys=template_keys,
            template_allowed_vars=base_vars,
        )

    def _validate_alarm_config(self):
        self.alarm_opt["strategy"] = self._validate_strategy(
            self.alarm_opt.get("strategy"),
            "config.alarm.strategy",
            CONFIG_DEFAULTS["alarm"]["strategy"],
        )
        base_vars = self._supported_alarm_template_vars()
        template_keys = CONFIG_SUPPORTED["templates"]["alarm_keys"]
        self.alarm_opt["template"] = _ensure_dict(self.alarm_opt.get("template"), "config.alarm.template")
        self._validate_template_obj(
            self.alarm_opt["template"],
            allowed_keys=template_keys,
            allowed_vars=base_vars,
            path="config.alarm.template",
        )
        self._validate_destinations(
            self.alarm_opt.get("destinations"),
            path="config.alarm.destinations",
            template_allowed_keys=template_keys,
            template_allowed_vars=base_vars,
        )

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
        except Exception as e:
            self.logging.error(f"❌ filter error: {e}")
            return False
        
    def check_filters(self, msg, filters):
        if filters:
            return all(self.is_filter_matched(msg, f['match'], f['type']) for f in filters)
        else:
            return True
    
    def _resolve_destination(self, destination):
        target_name = destination['target']
        target_cfg = self.target_opt[target_name]
        channel_name = target_cfg['channel']
        channel_cfg = self.channel_opt.get(channel_name) or {}
        merged = _deep_merge_dicts(channel_cfg, target_cfg)
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
    
    def _send_to_destination(self, payload, title, body, code=None):
        notify = self.channel_notifiers[payload["channel"]]
        return notify(payload, title, body, code=code)

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
            strategy = self.alarm_opt.get('strategy') or CONFIG_DEFAULTS["alarm"]["strategy"]
            merged_base_template = _deep_merge_dicts(
                CONFIG_DEFAULTS["alarm"]["template"],
                self.alarm_opt.get('template', {})
            )

            any_success = False
            any_failed = False
            for dest in self.alarm_destinations:
                merged_template = _deep_merge_dicts(merged_base_template, dest.get('template', {}))
                title, body = self.gen_alarm_msg(msg, merged_template, **kwargs)
                cur_status, cur_res = self._send_to_destination(dest, title, body, code=msg.get('code'))
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
            self.logging.info(f"{"#" * 15} ⚠️ alarm finished {"#" * 15}")

    def gen_fwd_msg(self, msg, msg_template, **kwargs):
        mapping = self._build_tmpl_mapping(msg, **kwargs)
        fwd_msg_title = _render_template(msg_template.get('title'), mapping)
        fwd_msg_body = _render_template(msg_template.get('body'), mapping)
        if msg.get('code') and msg_template.get('title_code'):
            fwd_msg_body = f"{fwd_msg_title}\n{fwd_msg_body}"
            fwd_msg_title = _render_template(msg_template.get('title_code'), mapping)
        return fwd_msg_title, fwd_msg_body

    def forward_message(self, msg):
        strategy = self.fwd_opt.get('strategy') or CONFIG_DEFAULTS["forward"]["strategy"]
        merged_base_template = _deep_merge_dicts(
            CONFIG_DEFAULTS["forward"]["template"],
            self.fwd_opt.get('template', {})
        )

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

            merged_template = _deep_merge_dicts(merged_base_template, dest.get('template', {}))
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
            self.send_alarm(error="no message received for 24h")
            self.last_new_msg_time = c_timestamp
    
    def update_hook(self):
        try:
            self._check2notify()
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())