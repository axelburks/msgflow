import os
import re
import time
import logging
import sqlite3
import re
import datetime

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
    def __init__(self, db_file, fwd_opt):
        super(SMSFlow, self).__init__()
        self.db_file = db_file
        self.db = LiteDB(self.db_file)
        self.fwd_opt = fwd_opt
        ctimestamp = int(time.time())
        self.min_update_time = ctimestamp
        self.update_time = { "notify_time": ctimestamp }
        for key, value in fwd_opt['destinations'].items():
            for item in value:
                name_mark = item['name_mark']
                self.update_time[f"{key}_{name_mark}"] = ctimestamp
    
    def get_message(self):
        sql = """
        select
            message.rowid,
            ifnull(handle.uncanonicalized_id, chat.chat_identifier) AS sender,
            message.service,
            (message.date / 1000000000 + 978307200) AS message_date,
            message.text,
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
            and text is not null
            and length(text) > 0
        order by
            message.date desc
        limit 10
        """
        data = self.db.select(sql)
        return data
    
    def get_msg_with_code(self):
        self.logging.debug('select db')
        msgs = self.get_message()
        self.logging.debug(msgs)
        self.logging.debug('self.min_update_time:' + str(self.min_update_time))
        result = []
        
        pattern_flags = r'(?<!回复|获取)验证(密)?码|授权码|校验码|检验码|确认码|激活码|动态码|安全码|(验证)?代码|校验代码|检验代码|激活代码|确认代码|动态代码|安全代码|登入码|认证码|识别码|短信口令|动态密码|交易码|上网密码|动态口令|随机码|驗證碼|授權碼|校驗碼|檢驗碼|確認碼|激活碼|動態碼|(驗證)?代碼|校驗代碼|檢驗代碼|確認代碼|激活代碼|動態代碼|登入碼|認證碼|識別碼|一次性密码|一次性密碼|[Cc][Oo][Dd][Ee]|[Vv]erification|[Vv]alidation|[Ss]ecurity [Cc]ode'
        pattern_captchas = r'(?<![A-Za-z0-9])[0-9-]{4,8}(?![A-Za-z0-9]|\]-|\] -|-| -)'
        
        for i in msgs:
            # Returns only the sms since the last update or forwarding was successful
            if i['message_date'] > self.min_update_time:
                msg_escaped = re.sub(r'((https?|ftp|file):\/\/|www\.)[-A-Z0-9+&@#\/%?=~_|$!:,.;]*[A-Z0-9+&@#\/%=~_|$]|\n', ' ', i['text'], flags=re.I)

                match_flags = re.search(pattern_flags, msg_escaped, flags=re.I)
                matches_captchas = re.findall(pattern_captchas, msg_escaped)
                
                if match_flags and matches_captchas:
                    flag_index = msg_escaped.find(match_flags.group())
                    closest_captcha = min(matches_captchas, key=lambda x: abs(msg_escaped.find(x) - flag_index))
                    i['code'] = closest_captcha
                result.append(i)
                
        return result
    
    def _notify(self):
        msg_new = self.get_msg_with_code()
        msg_new.reverse()
        self.logging.debug(msg_new)
        if msg_new:            
            for temp in msg_new:
                sms_code = None
                receive_timestamp = temp['message_date']
                
                # notify message
                if receive_timestamp > self.update_time['notify_time'] and 'code' in temp:
                    sms_code = temp['code']
                    self.notification(sms_code, temp['text'])
                    self.save_to_clipboard(sms_code)
                    self.update_time['notify_time'] = receive_timestamp
                    
                # forward messagge
                fwd_filter_matched = False
                for filter_item in self.fwd_opt['filter']:
                    if temp[filter_item] in self.fwd_opt['filter'][filter_item]:
                        fwd_filter_matched = True
                if fwd_filter_matched:
                    receive_timestring = datetime.datetime.fromtimestamp(receive_timestamp)
                    msg_sender = f"{temp['receiver']} <- {temp['sender']}"
                    msg_text = f"{temp['text']}\n{self.fwd_opt['source']} - {receive_timestring}"
                    for fwd_dest in self.fwd_opt['destinations']:
                        if fwd_dest == 'bark':
                            bark_title = f"🌀 {sms_code}" if sms_code else msg_sender
                            bark_body_head = f"{msg_sender}\n" if sms_code else ''
                            bark_body = f"{bark_body_head}{msg_text}"
                            for bark_dest in self.fwd_opt['destinations'][fwd_dest]:
                                fwd_all = bark_dest.get('scope') == 'all'
                                if (fwd_all or 'code' in temp) and receive_timestamp > self.update_time[f"{fwd_dest}_{bark_dest['name_mark']}"]:
                                    bark_status, bark_res = self.notify_to_bark(bark_dest, bark_title, bark_body, sms_code)
                                    self.logging.debug(bark_res)
                                    if bark_status:
                                        self.update_time[f"{fwd_dest}_{bark_dest['name_mark']}"] = receive_timestamp
                                    else:
                                        self.notification("Bark 发送失败", bark_res)
                        if fwd_dest == 'tgbot':
                            tgbot_body = f"{msg_sender}\n{msg_text}"
                            for tgbot_dest in self.fwd_opt['destinations'][fwd_dest]:
                                fwd_all = tgbot_dest.get('scope') == 'all'
                                if (fwd_all or 'code' in temp) and receive_timestamp > self.update_time[f"{fwd_dest}_{tgbot_dest['name_mark']}"]:
                                    tgbot_status, tgbot_res = self.notify_to_tgbot(tgbot_dest, tgbot_body)
                                    self.logging.debug(tgbot_res)
                                    if tgbot_status:
                                        self.update_time[f"{fwd_dest}_{tgbot_dest['name_mark']}"] = receive_timestamp
                                    else:
                                        self.notification("TGBot 发送失败", tgbot_res)
                    self.min_update_time = min(self.update_time.values())
                else:
                    self.min_update_time = receive_timestamp
    
    def update_hook(self):
        self.logging.debug('checking')
        self.logging.debug(self.fwd_opt)
        # update_time = int(os.path.getmtime(self.db_file))
        # self.logging.debug('dbfile update_time: ' + str(update_time))
        # tp = abs(update_time - self.update_time)
        # self.logging.debug("tp: " + str(tp))
        # if not tp and tp <= 15:
        #     self.update_time = update_time
        #     self._notify()
        self._notify()