import os, sys, time, datetime, json, sqlite3, traceback, copy, random
import regex, typedstream

from base import Base, CHANNEL_NOTIFIERS, render_destination
import config

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
        self.is_1st_start = True
        self.update_time = {}
        saved_update_time = None
        self.built_cfg = config.cfg.built_cfg
        self.forward_rules = self.built_cfg['forward']['rules']
        self.forward_destinations = self._flatten_forward_destinations()
        self.alarm_strategy = self.built_cfg['alarm']['strategy']
        self.alarm_destinations = self.built_cfg['alarm']['destinations']
        self.source = self.built_cfg.get('source')
        self.last_fwd_time_file = config.cfg.record_file_path
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
    
    def mock2notify(self, num): 
        with open(os.path.expanduser(f"./sms/sms.json"), 'r') as f:
            msgs_list = json.load(f)
        if not isinstance(msgs_list, list):
            raise ValueError(f"invalid sms.json format, expected list, got {type(msgs_list)}")
        actual_num = min(len(msgs_list), num)
        new_msgs = random.sample(msgs_list, actual_num)
        self.init_update_time({})

        for idx, msg in enumerate(new_msgs):
            msg["timestamp"] = self.min_update_time + idx + 1
            msg["time_str"] = _format_ts(msg["timestamp"])
        
        try:
            self.send_alarm(error="mock starting")
            self.check2notify(mock=True, mock_msgs=new_msgs)
        except Exception as e:
            traceback.print_exc()
            self.send_alarm(error=str(e), traceback=traceback.format_exc())

    def check_forward_destinations(self):
        for dest in self.forward_destinations:
            try:
                dest_name = dest.get('name_mark')
                dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
                check_title = f"{dest_mark} check passed"
                check_msg = {"source": self.source}
                rendered_dest = render_destination(dest, check_msg, is_alarm=True, error=check_title)
                cur_status, cur_res = self._send_to_destination(rendered_dest)
                if not cur_status:
                    self.logging.error(f"❌ {dest_mark} error: {cur_res}")
                    sys.exit(1)
            except Exception as e:
                self.logging.error(f"❌ {dest_mark} error: {e}")
                sys.exit(1)

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

    def _flatten_forward_destinations(self):
        flat = []
        for rule in self.forward_rules:
            flat.extend(rule['destinations'])
        return flat
    
    def _send_to_destination(self, dest):
        notify = CHANNEL_NOTIFIERS[dest["channel"]]
        return notify(self, dest)

    def send_alarm(self, msg: dict = {}, **kwargs) -> bool:
        self.logging.info(f"{'#' * 15} ⚠️  alarm start {'#' * 15}")
        try:
            msg['source'] = self.source

            any_success = False
            any_failed = False
            for dest in self.alarm_destinations:
                rendered_dest = render_destination(dest, msg, is_alarm=True, **kwargs)
                cur_status, cur_res = self._send_to_destination(rendered_dest)
                if cur_status:
                    any_success = True
                    if self.alarm_strategy == 'until_success':
                        return True
                else:
                    any_failed = True
                    self.logging.error(f"❌ alarm failed: {cur_res}")
            if self.alarm_strategy == 'all':
                return not any_failed
            return any_success
        finally:
            self.logging.info(f"{'#' * 15} ⚠️  alarm end {'#' * 15}")

    def forward_message(self, msg):
        msg['source'] = self.source
        msg_ts = msg.get('timestamp')
        overall_ok = True
        for rule in self.forward_rules:
            rule_name = rule.get('name_mark')
            rule_filters = rule.get('filters')
            rule_strategy = rule.get('strategy')
            rule_dests = rule.get('destinations')
            self.logging.info(f"📏 {rule_name}({rule_strategy})")

            if not self.check_filters(msg, rule_filters):
                for dest in rule_dests:
                    dest_name = dest["name_mark"]
                    if msg_ts > self.update_time.get(dest_name, 0):
                        self.update_time[dest_name] = msg_ts
                continue

            attempted = 0
            any_success = False
            any_failed = False
            errors = []

            for idx, dest in enumerate(rule_dests):
                dest_name = dest["name_mark"]
                dest_mark = f"{dest.get('logmarker')} {dest_name}({dest.get('channel')})"
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

                rendered_dest = render_destination(dest, msg, is_alarm=False)
                cur_status, cur_res = self._send_to_destination(rendered_dest)

                attempted += 1
                if cur_status:
                    any_success = True
                    self.update_time[dest_name] = msg_ts
                    if rule_strategy == "until_success":
                        for remaining in rule_dests[idx + 1:]:
                            r_name = remaining["name_mark"]
                            if msg_ts > self.update_time.get(r_name, 0):
                                self.update_time[r_name] = msg_ts
                        break
                else:
                    any_failed = True
                    self.logging.error(f"❌ forward failed: {cur_res}")
                    errors.append(f"{cur_res}")

            if rule_strategy == "all":
                if attempted > 0 and any_failed:
                    overall_ok = False
                    self.send_alarm(
                        msg,
                        error=f"({rule_strategy}) some forward destinations failed",
                        traceback="\n\n".join(errors) if errors else None,
                    )
            else:
                if attempted > 0 and (not any_success):
                    overall_ok = False
                    self.send_alarm(
                        msg,
                        error=f"({rule_strategy}) all destinations failed",
                        traceback="\n\n".join(errors) if errors else None,
                    )

        return overall_ok
    
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
            for msg in new_msgs:
                try:
                    print("")
                    self.logging.info(f"{'>' * 15} 📩 new message {'<' * 15}")
                    msg['time_str'] = _format_ts(msg.get('timestamp', 0))
                    self.logging.info(f"📨 {json.dumps(msg, ensure_ascii=False)}")
                    msg['msg'] = json.dumps(msg, ensure_ascii=False, default=str)
                    msg['code'] = self.get_code_from_text(msg.get('text'))
                    if msg['code']:
                        self.logging.info(f"🔐 {msg['code']}")
                    self.forward_message(msg)
                except Exception as e:
                    traceback.print_exc()
                    self.send_alarm(msg=msg, error=str(e), traceback=traceback.format_exc())
                    continue
                finally:
                    self.logging.info(f"{'>' * 15} ✉️ done {'<' * 15}")

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