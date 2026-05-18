import plistlib, logging
from typing import Any, Optional

from .base import MsgFlow
from ..litedb import LiteDB
from ...common.paths import notify_db_path
from ...common.utils import get_app_name, format_ts, MAC_EPOCH_OFFSET

logger = logging.getLogger(__name__)


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

    def __init__(self, runtime: Any = None) -> None:
        self.db = LiteDB(db_file=str(notify_db_path()))
        super().__init__(runtime=runtime)

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
                app.identifier,
                record.delivered_date,
                record.data
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
                    plist_data = plistlib.loads(bytes(row.get('data')))
                except Exception as e:
                    logger.error(f"❌ notify plist decode error: {e}")
                    continue

                req = plist_data.get('req') or {}
                title = _extract_req_field(req, 'titl')
                subtitle = _extract_req_field(req, 'subt')
                body = _extract_req_field(req, 'body')

                # Silent pushes (no textual content) are not user-visible; skip.
                if not (title or subtitle or body):
                    continue

                # App identity can live either on the plist ('app' key) or on
                # the row's `identifier` column; prefer the plist value when present.
                bundle_id = plist_data.get('app') or row.get('identifier')
                sender = get_app_name(bundle_id)

                # Mac absolute time -> Unix epoch for templates/logs. `delivered_date`
                # is also kept at the top level because it is the cursor field.
                delivered_date = float(row.get('delivered_date'))
                timestamp = delivered_date + MAC_EPOCH_OFFSET

                row['app'] = plist_data.get('app')
                row['req'] = {
                    'titl': title,
                    'subt': subtitle,
                    'body': body,
                }
                row.pop('data', None)

                msg = {
                    'delivered_date': delivered_date,
                    'sender': sender,
                    'title': title,
                    'subtitle': subtitle,
                    'body': body,
                    'time_str': format_ts(timestamp),
                    'timestamp': timestamp,
                    'msg': row,
                }
                
                results.append(msg)
            except Exception as e:
                logger.error(f"❌ notify row parse error: {e}")
                continue
        return results
