from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .base import MsgFlow
from .ipn_store import RemoteNotificationStore
from .ipn_watcher import IPNFileWatcher
from ...common.paths import ipn_remote_path


logger = logging.getLogger(__name__)


class IPNFlow(MsgFlow):
    """Flow implementation for iPhone notifications mirrored to macOS."""

    KIND = "ipn"
    NEW_MSG_HIT = "📱 new"
    DONE_MSG_HIT = "📱 done"
    CURSOR_FIELD = "ipn_cursor"
    FALLBACK_SCAN_SECONDS = 60.0

    def __init__(self, runtime: Any = None, root_path: Optional[Path] = None, start_watcher: bool = True) -> None:
        self.root_path = root_path or ipn_remote_path()
        self.store = RemoteNotificationStore(self.root_path)
        self._pending_app_uuids: set[str] = set()
        self._force_full_scan = True
        self._dirty = True
        self._last_full_scan_at = 0.0
        self._state_lock = threading.RLock()
        self._watcher: IPNFileWatcher | None = None
        super().__init__(runtime=runtime)
        if start_watcher:
            self._watcher = IPNFileWatcher(self.root_path, self._on_file_changed)
            self._watcher.start()
            if not self._watcher.available:
                logger.info("ipn file watcher is unavailable; using fallback scans")

    def initial_cursor(self) -> int:
        # Start fresh destinations at the current mirrored-notification tail.
        return self.store.max_cursor()

    def _on_file_changed(self, changed_paths: set[Path]) -> None:
        with self._state_lock:
            for path in changed_paths:
                if path.name == "Library.plist" or path == self.root_path:
                    self._force_full_scan = True
                    continue
                if path.name == "DeliveredNotifications.plist":
                    self._pending_app_uuids.add(path.parent.name.upper())
                elif path.parent == self.root_path:
                    self._pending_app_uuids.add(path.name.upper())
                else:
                    self._force_full_scan = True
            self._dirty = True
        if self.runtime is not None:
            request = getattr(self.runtime, "request_source_check", None)
            if callable(request):
                request(self.KIND)

    def _fallback_scan_due(self) -> bool:
        return (time.monotonic() - self._last_full_scan_at) >= self.FALLBACK_SCAN_SECONDS

    def update_hook(self) -> None:
        with self._state_lock:
            should_scan = self._dirty or self._fallback_scan_due()
            if self._fallback_scan_due():
                self._force_full_scan = True
        if not should_scan:
            return
        super().update_hook()

    def query_new_msgs(self) -> list[dict[str, Any]]:
        with self._state_lock:
            force_full_scan = self._force_full_scan
            app_uuids = None if force_full_scan else set(self._pending_app_uuids)
            self._pending_app_uuids.clear()
            self._force_full_scan = False
            self._dirty = False
            if force_full_scan:
                self._last_full_scan_at = time.monotonic()
        if app_uuids is not None and not app_uuids:
            return []
        messages = self.store.load_notifications(app_uuids=app_uuids)
        min_cursor = int(self.min_cursor)
        return [msg for msg in messages if int(msg["ipn_cursor"]) > min_cursor]

    def close(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        super().close()
