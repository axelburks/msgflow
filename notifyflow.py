import os, plistlib, logging
from typing import Any, Optional

from msgflow import MsgFlow
from litedb import LiteDB
from utils import get_app_name

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
    MOCK_FILE = "./notify/notify.json"

    def __init__(self) -> None:
        self.db = LiteDB(db_file=notify_db_file_path)
        super().__init__()

    def query_new_msgs(self) -> list[dict[str, Any]]:
        # SQL converts Mac absolute time (2001 epoch) to Unix timestamp so the
        # Python side does no conversion.
        # The +0.00001s offset works around precision loss: record.json keeps
        # time_str only up to microseconds (6 digits), and when re-read the
        # value can be ~1μs smaller than the original double. A strict `>` would
        # then re-select the same record and cause duplicate forwarding.
        # Empirical min spacing between adjacent notifications is ~370μs, far
        # above 10μs, so we won't miss the next record either.
        ts_cursor = self.min_update_time + 0.00001
        sql = """
            SELECT
                record.rec_id,
                app.identifier AS app_identifier,
                (record.delivered_date + 978307200) AS timestamp,
                record.data AS data
            FROM record
            JOIN app USING (app_id)
            WHERE record.delivered_date IS NOT NULL
              AND (record.delivered_date + 978307200) > ?
            ORDER BY record.delivered_date
        """
        rows = self.db.select(sql, (ts_cursor,))

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

                msg = {
                    'rec_id': row.get('rec_id'),
                    'sender': sender,
                    'receiver': receiver,
                    'timestamp': float(row.get('timestamp')),
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
