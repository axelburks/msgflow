from __future__ import annotations

import hashlib
import logging
import plistlib
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from ...common.utils import MAC_EPOCH_OFFSET, format_ts


logger = logging.getLogger(__name__)
CURSOR_SCALE = 1_000_000
DECODE_RETRY_ATTEMPTS = 3
DECODE_RETRY_DELAY_SECONDS = 0.2


def creation_date_to_cursor(value: float) -> int:
    return int(float(value) * CURSOR_SCALE)


def _decode_keyed_archive(path: Path) -> Any:
    data = plistlib.loads(path.read_bytes())
    objects = data.get("$objects", []) if isinstance(data, dict) else []
    seen: dict[int, Any] = {}

    def class_name(obj: Any) -> Optional[str]:
        if not isinstance(obj, dict):
            return None
        class_ref = obj.get("$class")
        if not isinstance(class_ref, plistlib.UID) or class_ref.data >= len(objects):
            return None
        class_obj = objects[class_ref.data]
        if not isinstance(class_obj, dict):
            return None
        name = class_obj.get("$classname")
        return str(name) if name else None

    def decode(value: Any) -> Any:
        if isinstance(value, plistlib.UID):
            idx = value.data
            if idx in seen:
                return seen[idx]
            if idx >= len(objects):
                return None
            return decode_object(idx, objects[idx])
        if isinstance(value, list):
            return [decode(item) for item in value]
        if isinstance(value, dict):
            return {key: decode(val) for key, val in value.items() if key != "$class"}
        return value

    def decode_object(idx: int, obj: Any) -> Any:
        name = class_name(obj)
        if name in ("NSDictionary", "NSMutableDictionary") and isinstance(obj, dict):
            out: dict[Any, Any] = {}
            seen[idx] = out
            keys = [decode(key) for key in obj.get("NS.keys", [])]
            values = [decode(val) for val in obj.get("NS.objects", [])]
            out.update(zip(keys, values))
            return out
        if name in ("NSArray", "NSMutableArray") and isinstance(obj, dict):
            out: list[Any] = []
            seen[idx] = out
            out.extend(decode(item) for item in obj.get("NS.objects", []))
            return out
        if name == "NSDate" and isinstance(obj, dict):
            return float(obj.get("NS.time", 0)) + MAC_EPOCH_OFFSET
        if name == "NSUUID" and isinstance(obj, dict):
            raw = obj.get("NS.uuidbytes")
            if isinstance(raw, bytes) and len(raw) == 16:
                return str(uuid.UUID(bytes=raw)).upper()
        if isinstance(obj, dict):
            out: dict[Any, Any] = {}
            seen[idx] = out
            out.update({key: decode(val) for key, val in obj.items() if key != "$class"})
            return out
        return obj

    top = data.get("$top", {}) if isinstance(data, dict) else {}
    return decode(top.get("root"))


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, (bytes, bytearray)):
            try:
                value = bytes(value).decode("utf-8", errors="replace")
            except Exception:
                continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _build_text(title: str, subtitle: str, body: str) -> str:
    return "\n".join(part for part in (title, subtitle, body) if part)


def _fallback_notification_id(app_uuid: str, created_at: float, title: str, body: str) -> str:
    digest = hashlib.sha256(f"{app_uuid}\0{created_at:.6f}\0{title}\0{body}".encode("utf-8")).hexdigest()
    return digest[:16]


class RemoteNotificationStore:
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path
        self._bundle_by_uuid: dict[str, str] = {}

    @property
    def library_path(self) -> Path:
        return self.root_path / "Library.plist"

    def refresh_library(self) -> None:
        if not self.library_path.exists():
            self._bundle_by_uuid = {}
            return
        try:
            mapping = _decode_keyed_archive(self.library_path)
        except Exception as e:
            logger.warning(
                "failed to decode iPhone notification library %s; keeping the previous app mapping: %s",
                self.library_path,
                e,
            )
            return
        if not isinstance(mapping, dict):
            logger.warning(
                "unexpected iPhone notification library format %s; keeping the previous app mapping",
                self.library_path,
            )
            return
        self._bundle_by_uuid = {
            str(app_uuid).upper(): str(bundle_id)
            for bundle_id, app_uuid in mapping.items()
            if bundle_id and app_uuid
        }

    def max_cursor(self) -> int:
        max_value = 0
        for msg in self.load_notifications():
            max_value = max(max_value, int(msg["ipn_cursor"]))
        return max_value

    def load_notifications(self, app_uuids: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
        self.refresh_library()
        if app_uuids is None:
            dirs = [path for path in self.root_path.iterdir() if path.is_dir()] if self.root_path.exists() else []
        else:
            dirs = [self.root_path / str(app_uuid).upper() for app_uuid in app_uuids]

        messages: list[dict[str, Any]] = []
        for app_dir in dirs:
            delivered_path = app_dir / "DeliveredNotifications.plist"
            if not delivered_path.exists():
                continue
            try:
                delivered_items = self._load_delivered_items_with_retry(delivered_path)
            except Exception as e:
                logger.warning(
                    "failed to decode iPhone notifications after retries %s: %s",
                    delivered_path,
                    e,
                )
                continue
            for item in delivered_items:
                msg = self._message_from_item(app_dir.name.upper(), item)
                if msg is not None:
                    messages.append(msg)
        return sorted(messages, key=lambda msg: int(msg["ipn_cursor"]))

    def _load_delivered_items(self, path: Path) -> list[dict[str, Any]]:
        root = _decode_keyed_archive(path)
        items = root if isinstance(root, list) else [root]
        return [item for item in items if isinstance(item, dict)]

    def _load_delivered_items_with_retry(self, path: Path) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(DECODE_RETRY_ATTEMPTS):
            try:
                return self._load_delivered_items(path)
            except Exception as e:
                last_error = e
                if attempt < DECODE_RETRY_ATTEMPTS - 1:
                    time.sleep(DECODE_RETRY_DELAY_SECONDS)
        assert last_error is not None
        raise last_error

    def _message_from_item(self, app_uuid: str, item: dict[str, Any]) -> Optional[dict[str, Any]]:
        created_at = item.get("AppNotificationCreationDate")
        if not isinstance(created_at, (int, float)):
            return None
        title = _first_text(item.get("AppNotificationTitle"), item.get("Header"))
        subtitle = _first_text(item.get("Footer"), item.get("AppNotificationSubtitle"))
        body = _first_text(item.get("AppNotificationMessage"), item.get("body"))
        text = _build_text(title, subtitle, body)
        if not text:
            return None
        bundle_id = self._bundle_by_uuid.get(app_uuid, app_uuid)
        notification_id = _first_text(item.get("AppNotificationIdentifier")) or _fallback_notification_id(
            app_uuid,
            float(created_at),
            title,
            body,
        )
        timestamp = float(created_at)
        return {
            "ipn_cursor": creation_date_to_cursor(timestamp),
            "timestamp": timestamp,
            "time_str": format_ts(timestamp),
            "created_at": timestamp,
            "app_uuid": app_uuid,
            "notification_id": notification_id,
            "sender": bundle_id,
            "receiver": bundle_id,
            "title": title,
            "subtitle": subtitle,
            "body": body,
            "text": text,
        }
