import os
import re
import time
import logging
import sqlite3
import re
import datetime
import typedstream

from base import Base

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
    def __init__(self, db_file, fwd_opt, last_fwd_time_file, last_fwd_time):
        super(SMSFlow, self).__init__()
        self.db_file = db_file
        self.db = LiteDB(self.db_file)
        self.fwd_opt = fwd_opt
        self.template = {
            "title": "{{receiver}} <- {{sender}}",
            "body": "{{text}}\n{{source}} - {{receive_time}}"
        }
        self.last_fwd_time_file = last_fwd_time_file
        self.min_update_time = last_fwd_time
        self.update_time = { "notify_time": int(time.time()) }
        for key, value in fwd_opt['destinations'].items():
            for item in value:
                name_mark = item['name_mark']
                self.update_time[f"{key}_{name_mark}"] = last_fwd_time
    
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
        """
        data = self.db.select(sql.format(min_update_time=self.min_update_time))
        for row in data[:]:
            if not row['text']:
                if row['attributedBody']:
                    msg_text = self.get_msg_from_applearchive(row['attributedBody'])
                    row['text'] = msg_text
                    row['attributedBody'] = msg_text
                else:
                    data.remove(row)
            else:
                row['attributedBody'] = ''
        return data
    
    def get_msg_with_code(self):
        self.logging.debug(self.update_time)
        self.logging.debug('self.min_update_time:' + str(self.min_update_time))
        msgs = self.get_message()
        result = []
        
        pattern_flags = r'(?<!回复|获取)验证(密)?码|授权码|校验码|检验码|确认码|激活码|动态码|安全码|(验证)?代码|校验代码|检验代码|激活代码|确认代码|动态代码|安全代码|登入码|认证码|识别码|短信口令|动态密码|交易码|上网密码|动态口令|随机码|驗證碼|授權碼|校驗碼|檢驗碼|確認碼|激活碼|動態碼|(驗證)?代碼|校驗代碼|檢驗代碼|確認代碼|激活代碼|動態代碼|登入碼|認證碼|識別碼|一次性密码|一次性密碼|[Cc][Oo][Dd][Ee]|[Vv]erification|[Vv]alidation|[Ss]ecurity [Cc]ode'
        pattern_captchas = r'(?<![A-Za-z0-9])[0-9-]{4,8}(?![A-Za-z0-9]|\]-|\] -|-| -)'
        
        for i in msgs:
            msg_escaped = re.sub(r'((https?|ftp|file):\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|$!:,.;]*[A-Z0-9+&@#\/%=~_|$]|\n', ' ', i['text'], flags=re.I)

            match_flags = re.search(pattern_flags, msg_escaped, flags=re.I)
            matches_captchas = re.findall(pattern_captchas, msg_escaped)
            
            if match_flags and matches_captchas:
                flag_index = msg_escaped.find(match_flags.group())
                closest_captcha = min(matches_captchas, key=lambda x: abs(msg_escaped.find(x) - flag_index))
                i['code'] = closest_captcha
            result.append(i)
                
        return result
    
    def is_filter_matched(self, msg, match, match_type):
        try:
            if match_type == 'and':
                return all(key in msg and re.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'or':
                return any(key in msg and re.match(str(pattern), str(msg[key])) for key, pattern in match.items())
            elif match_type == 'selector':
                return all((pattern == 'have' and key in msg) or (pattern == 'none' and key not in msg) for key, pattern in match.items())
        except re.error as e:
            self.logging.error(f"Regex error: {e}")
            return False
        
    def check_filters(self, msg, filters):
        if filters:
            return all(self.is_filter_matched(msg, f['match'], f['type']) for f in filters)
        else:
            return True
    
    def gen_fwd_msg(self, msg, msg_template):
        def template_repl(otemplate):
            return otemplate.replace('{{sender}}', msg['sender'])\
                            .replace('{{receiver}}', msg['receiver'])\
                            .replace('{{text}}', msg['text'])\
                            .replace('{{msg_code}}', msg.get('code', ''))\
                            .replace('{{source}}', self.fwd_opt.get('source', 'Monitor'))\
                            .replace('{{receive_time}}', str(datetime.datetime.fromtimestamp(msg['message_date'])))
        
        fwd_msg_title = template_repl(msg_template['title']) if msg_template.get('title') else ''
        fwd_msg_body = template_repl(msg_template['body']) if msg_template.get('body') else ''
        fwd_msg_title_code = template_repl(msg_template['title_code']) if msg_template.get('title_code') and 'code' in msg else ''
        if fwd_msg_title_code:
            fwd_msg_body = f"{fwd_msg_title}\n{fwd_msg_body}"
            fwd_msg_title = fwd_msg_title_code
        return fwd_msg_title, fwd_msg_body
            
    def forward(self, msg, fwd_dest="bark"):
        c_template = {**self.template, **self.fwd_opt.get('template', {})}

        for cur_dest in self.fwd_opt['destinations'][fwd_dest]:
            uptime_key = f"{fwd_dest}_{cur_dest['name_mark']}"
            all_filters_matched = self.check_filters(msg, cur_dest.get('filters'))
            if all_filters_matched:
                if msg['message_date'] > self.update_time[uptime_key]:
                    c_template.update(cur_dest.get('template', {}))
                    fwd_msg_title, fwd_msg_body = self.gen_fwd_msg(msg, c_template)
                    
                    if fwd_dest == 'bark':
                        cur_status, cur_res = self.notify_to_bark(cur_dest, fwd_msg_title, fwd_msg_body, msg.get('code'))
                    elif fwd_dest == 'tgbot':
                        cur_status, cur_res = self.notify_to_tgbot(cur_dest, fwd_msg_title, fwd_msg_body, msg.get('code'))
                    else:
                        self.logging.error(f"Unsupported forward type: {fwd_dest}, skipping...")
                        return False
                    self.logging.debug(cur_res)
                    if cur_status:
                        self.update_time[uptime_key] = msg['message_date']
                    else:
                        self.logging.error(f"{uptime_key} 发送失败:{cur_res}")
                        self.notification(f"{uptime_key} 发送失败", cur_res)
                        return False
            else:
                 self.update_time[uptime_key] = msg['message_date']
        return True
                
                        
    def _notify(self):
        msgs_with_code = self.get_msg_with_code()
        self.logging.debug(msgs_with_code)

        if msgs_with_code:
            for temp in msgs_with_code:
                # notify message
                if temp['message_date'] > self.update_time['notify_time'] and temp.get('code'):
                    self.notification(temp['code'], temp['text'])
                    self.save_to_clipboard(temp['code'])
                    self.update_time['notify_time'] = temp['message_date']
                    
                # forward messagge
                for fwd_dest in self.fwd_opt['destinations']:
                    if not self.forward(temp, fwd_dest):
                        return False
                self.min_update_time = min(self.update_time.values())
                with open(self.last_fwd_time_file, 'w') as file:
                    file.write(str(self.min_update_time))
    
    def update_hook(self):
        self.logging.debug('checking')
        self._notify()