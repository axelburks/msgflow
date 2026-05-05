import os, plistlib, logging
from typing import Any, Optional

from msgflow import MsgFlow
from litedb import LiteDB
from utils import get_app_name, format_ts, MAC_EPOCH_OFFSET

logger = logging.getLogger(__name__)

notify_db_file_path = os.path.expanduser(
    '~/Library/Group Containers/group.com.apple.usernoted/db2/db'
)


def _extract_req_field(req: Any, key: str) -> Optional[str]:
    # Fields inside the `req` plist can be either str or raw bytes; normalize
    # both to a regular str (replacing undecodable bytes) so downstream
    # templates/logging never see a bytes value.
    if not isinstance(req, dict):
        return None
    val = req.get(key)
    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode('utf-8', errors='replace')
        except Exception:
            return None
    return val


def _build_text(title: Optional[str], subtitle: Optional[str], body: Optional[str]) -> str:
    # Join whichever of title/subtitle/body are non-empty into a single
    # newline-separated text, mirroring how the notification appears on screen.
    parts = [p for p in (title, subtitle, body) if p]
    return '\n'.join(parts)


class NotifyFlow(MsgFlow):
    """Flow implementation that reads macOS Notification Center records
    from the `usernoted` SQLite database."""

    KIND = "notify"
    NEW_MSG_HIT = "📬 new"
    DONE_MSG_HIT = "📭 done"
    NO_NEW_MSG_TEXT = "no notification received for 24h"
    # Cursor uses `record.delivered_date` in its raw Mac-absolute-time form
    # (seconds since 2001-01-01). Comparing the raw column in SQL lets
    # SQLite use any index that may exist on it and avoids recomputing the
    # Unix-epoch expression for every candidate row. The Unix-epoch value
    # is derived in Python and exposed on msg['timestamp'] for templates/logs.
    #
    # `delivered_date` is written at delivery time and is strictly increasing
    # across normal notifications. Unlike `rec_id` — which is `INTEGER
    # PRIMARY KEY` without AUTOINCREMENT and therefore gets reused after rows
    # are dismissed/deleted — `delivered_date` is unaffected by row deletions,
    # making it a correct monotonic cursor.
    CURSOR_FIELD = "delivered_date"
    MOCK_FILE = "./notify/notify.json"

    def __init__(self) -> None:
        self.db = LiteDB(db_file=notify_db_file_path)
        super().__init__()

    def initial_cursor(self) -> float:
        # Start fresh destinations at current DB tail (most recent delivery
        # timestamp) so we don't replay history.
        rows = self.db.select(
            "SELECT IFNULL(MAX(delivered_date), 0) AS max_dd FROM record "
            "WHERE delivered_date IS NOT NULL"
        )
        return float(rows[0]['max_dd']) if rows else 0.0

    def query_new_msgs(self) -> list[dict[str, Any]]:
        sql = """
            SELECT
                record.rec_id,
                app.identifier AS app_identifier,
                record.delivered_date,
                record.data AS data
            FROM record
            JOIN app USING (app_id)
            WHERE record.delivered_date IS NOT NULL
              AND record.delivered_date > ?
            ORDER BY record.delivered_date
        """
        rows = self.db.select(sql, (self.min_cursor,))

        results = []
        for row in rows:
            try:
                # `record.data` is a binary plist containing the notification request.
                try:
                    p = plistlib.loads(bytes(row.get('data')))
                except Exception as e:
                    logger.error(f"❌ notify plist decode error: {e}")
                    continue

                req = p.get('req') or {}
                title = _extract_req_field(req, 'titl')
                subtitle = _extract_req_field(req, 'subt')
                body = _extract_req_field(req, 'body')

                # Silent pushes (no textual content) are not user-visible; skip.
                if not (title or subtitle or body):
                    continue

                # App identity can live either on the plist ('app' key) or on
                # the row's `app_identifier` column (case may differ); prefer
                # the plist value when present.
                app_identifier = row.get('app_identifier')
                sender = p.get('app') or app_identifier
                # Map bundle ID to a human-readable app name when possible.
                receiver = get_app_name(sender) or sender

                # Mac absolute time -> Unix epoch for templates/logs. `delivered_date`
                # is also kept on the msg because it is the cursor field.
                delivered_date = float(row.get('delivered_date'))
                timestamp = delivered_date + MAC_EPOCH_OFFSET
                msg = {
                    'rec_id': row.get('rec_id'),
                    'sender': sender,
                    'receiver': receiver,
                    'delivered_date': delivered_date,
                    'timestamp': timestamp,
                    'time_str': format_ts(timestamp),
                    'title': title,
                    'subtitle': subtitle,
                    'body': body,
                    'text': _build_text(title, subtitle, body),
                }
                results.append(msg)
            except Exception as e:
                logger.error(f"❌ notify row parse error: {e}")
                continue

        return results
