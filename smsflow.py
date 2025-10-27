import os, time, datetime, json, sqlite3
import regex, typedstream

from base import config
from base import Base

message_db_file_path = os.path.expanduser('~/Library/Messages/chat.db')

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
        self.fwd_opt = config.user_config.get('forward', {})
        self.template = {
            "title": "{{receiver}} <- {{sender}}",
            "body": "{{text}}\n{{source}} - {{receive_time}}"
        }
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
        for key, value in self.fwd_opt['destinations'].items():
            for item in value:
                c_dest_name = f"{key}_{item['name_mark']}"
                if saved_update_time and c_dest_name in saved_update_time:
                    self.update_time[c_dest_name] = saved_update_time[c_dest_name]
                else:
                    self.update_time[c_dest_name] = init_timestamp
        self.update_time['notify_time'] = init_timestamp
        self.min_update_time = min(self.update_time.values())
        self.last_new_msg_time = init_timestamp
        
    def write_last_fwd_time_ro_file(self):
        self.is_1st_start = False
        with open(self.last_fwd_time_file, 'w') as f:
            json.dump(self.update_time, f, indent=4)
    
    def get_msg_from_applearchive(self, archived_object):
        msgs = []
        unarchived_object = typedstream.unarchive_from_data(archived_object)
        for content in unarchived_object.contents:
            for item in content.values:
                if isinstance(item, typedstream.types.foundation.NSMutableString):
                    msgs.append(item.value)
        return '\n'.join(msgs)

    def get_message(self):
        sql = """
        select
            message.rowid,
            ifnull(handle.uncanonicalized_id, chat.chat_identifier) AS sender,
            message.service,
            (message.date / 1000000000 + 978307200) AS message_date,
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
    
    def gen_fwd_msg(self, msg, msg_template):
        def template_repl(otemplate):
            return otemplate.replace('{{sender}}', msg.get('sender', ''))\
                            .replace('{{receiver}}', msg.get('receiver', ''))\
                            .replace('{{text}}', msg.get('text', ''))\
                            .replace('{{msg_code}}', msg.get('code') or '')\
                            .replace('{{source}}', self.fwd_opt.get('source', 'Monitor'))\
                            .replace('{{receive_time}}', str(datetime.datetime.fromtimestamp(msg.get('message_date', 0))))
        
        fwd_msg_title = template_repl(msg_template['title']) if msg_template.get('title') else ''
        fwd_msg_body = template_repl(msg_template['body']) if msg_template.get('body') else ''
        fwd_msg_title_code = template_repl(msg_template['title_code']) if msg_template.get('title_code') and msg.get('code') else ''
        if fwd_msg_title_code:
            fwd_msg_body = f"{fwd_msg_title}\n{fwd_msg_body}"
            fwd_msg_title = fwd_msg_title_code
        return fwd_msg_title, fwd_msg_body
            
    def forward(self, msg, fwd_dest):
        c_template = {**self.template, **self.fwd_opt.get('template', {})}

        for cur_dest in self.fwd_opt['destinations'][fwd_dest]:
            uptime_key = f"{fwd_dest}_{cur_dest['name_mark']}"
            if msg.get('message_date', 0) > self.update_time[uptime_key]:
                all_filters_matched = self.check_filters(msg, cur_dest.get('filters'))
                if all_filters_matched:
                    c_template.update(cur_dest.get('template', {}))
                    fwd_msg_title, fwd_msg_body = self.gen_fwd_msg(msg, c_template)
                    
                    if fwd_dest == 'bark':
                        cur_status, cur_res = self.notify_to_bark(cur_dest, fwd_msg_title, fwd_msg_body, msg.get('code'))
                    elif fwd_dest == 'tgbot':
                        cur_status, cur_res = self.notify_to_tgbot(cur_dest, fwd_msg_title, fwd_msg_body, msg.get('code'))
                    else:
                        self.logging.error(f"Unsupported forward type: {fwd_dest}, stopping...")
                        return False
                    self.logging.debug(cur_res)
                    if cur_status:
                        self.update_time[uptime_key] = msg.get('message_date', 0)
                    else:
                        self.logging.error(f"{uptime_key} 发送失败:{cur_res}")
                        self.notification(f"{uptime_key} 发送失败", str(cur_res))
                        return False
                else:
                    self.update_time[uptime_key] = msg.get('message_date', 0)
        return True
    
    def monitor2notify(self, title, body, dests):
        try:
            for fwd_dest in dests:
                for cur_dest in self.fwd_opt['destinations'][fwd_dest]:
                    if fwd_dest == 'bark':
                        self.logging.error(self.notify_to_bark(cur_dest, title, body, badge=1))
                    elif fwd_dest == 'tgbot':
                        self.logging.error(self.notify_to_tgbot(cur_dest, title, body))
        except Exception as e:
            self.logging.error(f"❌ Error occurred when sending message: {e}")
        
    def _check2notify(self):
        self.min_update_time = min(self.update_time.values())
        self.logging.debug(self.update_time)
        self.logging.debug('self.min_update_time:' + str(self.min_update_time))
        c_timestamp = int(time.time())
        
        msgs = self.get_message()
        if msgs:
            self.last_new_msg_time = c_timestamp
            self.logging.info(msgs)
            for temp in msgs:
                # get code from message
                temp['code'] = self.get_code_from_msg(temp.get('text'))
                # notify message
                if temp['message_date'] > self.update_time['notify_time']:
                    self.update_time['notify_time'] = temp['message_date']
                    if temp.get('code'):
                        self.notification(temp['code'], temp['text'])
                        self.save_to_clipboard(temp['code'])
                # forward messagge
                for fwd_dest in self.fwd_opt['destinations']:
                    if not self.forward(temp, fwd_dest):
                        self.write_last_fwd_time_ro_file()
                        return False

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
            self.monitor2notify(f"{self.fwd_opt.get('source')}: No message received for 24h", "", ["bark"])
            self.last_new_msg_time = c_timestamp
    
    def update_hook(self):
        self.logging.debug('checking')
        try:
            self._check2notify()
        except Exception as e:
            self.logging.error(f"Error occurred: {e}")
            self.monitor2notify(f"{self.fwd_opt.get('source')}: Error occurred", f"{e}", ["bark", "tgbot"])