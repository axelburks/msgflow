import os
from typing import Any
import typedstream

from msgflow import MsgFlow
from litedb import LiteDB

sms_db_file_path = os.path.expanduser('~/Library/Messages/chat.db')


def _extract_from_applearchive(archived_object: bytes) -> str:
    # Some iMessage rows store their text inside an NSKeyedArchiver blob
    # (message.attributedBody) instead of message.text. Decode the typedstream
    # archive and concatenate the NSString / NSMutableString payloads we find.
    content = []
    unarchived_object = typedstream.unarchive_from_data(archived_object)
    for content in unarchived_object.contents:
        for item in content.values:
            if isinstance(item, typedstream.types.foundation.NSMutableString) or isinstance(item, typedstream.types.foundation.NSString):
                content.append(item.value)
    return '\n'.join(content)


class SMSFlow(MsgFlow):
    """Flow implementation that reads incoming SMS / iMessage from the
    local macOS Messages SQLite database (`chat.db`)."""

    KIND = "sms"
    NEW_MSG_HIT = "📩 new"
    DONE_MSG_HIT = "✉️  done"
    NO_NEW_MSG_TEXT = "no sms received for 24h"
    MOCK_FILE = "./sms/sms.json"

    def __init__(self) -> None:
        self.db = LiteDB(db_file=sms_db_file_path)
        super().__init__()

    def query_new_msgs(self) -> list[dict[str, Any]]:
        # Pull every inbound message newer than the oldest per-destination cursor.
        # The Messages DB stores `date` in Mac absolute time with nanosecond
        # precision; convert to Unix epoch directly in SQL so Python side only
        # compares plain floats.
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
            and (message.date / 1000000000 + 978307200) > ?
        order by
            message.date
        """
        data = self.db.select(sql, (self.min_update_time,))
        # Normalize: drop rows with no textual content, falling back to decoding
        # attributedBody (typedstream blob) when the plain `text` column is empty.
        for row in data[:]:
            if not row.get('text'):
                if row.get('attributedBody'):
                    row['text'] = _extract_from_applearchive(row.get('attributedBody'))
                else:
                    data.remove(row)
            row.pop('attributedBody', None)
        return data
