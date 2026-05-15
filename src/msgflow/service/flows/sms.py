from typing import Any
import typedstream

from .base import MsgFlow
from ..litedb import LiteDB
from ...common.paths import sms_db_path
from ...common.utils import MAC_EPOCH_OFFSET, format_ts


def _extract_from_applearchive(archived_object: bytes) -> str:
    # Some iMessage rows store their text inside an NSKeyedArchiver blob
    # (message.attributedBody) instead of message.text. Decode the typedstream
    # archive and concatenate the NSString / NSMutableString payloads we find.
    text = []
    unarchived_object = typedstream.unarchive_from_data(archived_object)
    for content in unarchived_object.contents:
        for item in content.values:
            if isinstance(item, typedstream.types.foundation.NSMutableString) or isinstance(item, typedstream.types.foundation.NSString):
                text.append(item.value)
    return '\n'.join(text)


class SMSFlow(MsgFlow):
    """Flow implementation that reads incoming SMS / iMessage from the
    local macOS Messages SQLite database (`chat.db`)."""

    KIND = "sms"
    NEW_MSG_HIT = "📩 new"
    DONE_MSG_HIT = "✉️  done"
    NO_NEW_MSG_TEXT = "no sms received for 24h"
    # `message.ROWID` is assigned at local INSERT time and is strictly
    # monotonic w.r.t. DB-arrival order, which is what we actually want for
    # "forward once per row" semantics — even if `date` is older (e.g. SMS
    # that synced late from a flaky iPhone network).
    CURSOR_FIELD = "rowid"
    # chat.db stores `message.date` in nanoseconds of Mac absolute time.
    _NS_PER_SEC = 1_000_000_000

    def __init__(self, runtime: Any = None) -> None:
        self.db = LiteDB(db_file=str(sms_db_path()))
        super().__init__(runtime=runtime)

    def initial_cursor(self) -> int:
        # Start fresh destinations at current DB tail so we don't replay history.
        rows = self.db.select(
            "select ifnull(max(message.ROWID), 0) as max_rowid "
            "from message where is_from_me = 0"
        )
        return int(rows[0]['max_rowid']) if rows else 0

    def query_new_msgs(self) -> list[dict[str, Any]]:
        # Pull every inbound message with ROWID greater than the oldest
        # per-destination cursor. `date` is selected raw (Mac abs time in ns);
        # conversion to a Unix-epoch `timestamp` happens in Python so SQL does
        # no arithmetic per row and templates/logs still see a clean float.
        sql = """
        select
            message.ROWID AS rowid,
            ifnull(handle.uncanonicalized_id, chat.chat_identifier) AS sender,
            message.service,
            message.date,
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
            and message.ROWID > ?
        order by
            message.ROWID
        """
        data = self.db.select(sql, (self.min_cursor,))
        # Normalize each row:
        # - derive `timestamp` (Unix seconds, float) from raw ns-since-2001 `date`;
        #   `message.date` is declared nullable in chat.db, so defensively coerce
        #   a missing value to 0 rather than crashing the whole poll tick
        # - attach `time_str` for templates/logs
        # - drop rows with no textual content, falling back to decoding
        #   attributedBody (typedstream blob) when the plain `text` column is empty
        for row in data[:]:
            raw_date = row.get('date') or 0
            row['timestamp'] = float(raw_date) / self._NS_PER_SEC + MAC_EPOCH_OFFSET
            row['time_str'] = format_ts(row['timestamp'])
            if not row.get('text'):
                if row.get('attributedBody'):
                    row['text'] = _extract_from_applearchive(row.get('attributedBody'))
                else:
                    data.remove(row)
            row.pop('attributedBody', None)
        return data
