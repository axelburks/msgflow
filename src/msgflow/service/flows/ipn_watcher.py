from __future__ import annotations

import logging
import os
import select
import threading
import time
from pathlib import Path
from typing import Callable


logger = logging.getLogger(__name__)
O_EVTONLY = 0x8000


class IPNFileWatcher:
    def __init__(
        self,
        root_path: Path,
        callback: Callable[[set[Path]], None],
        debounce_seconds: float = 0.5,
    ) -> None:
        self.root_path = root_path
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._kqueue: select.kqueue | None = None
        self._fds: dict[int, Path] = {}
        self._registered_paths: set[Path] = set()

    @property
    def available(self) -> bool:
        return hasattr(select, "kqueue") and hasattr(select, "kevent")

    def start(self) -> None:
        if self._thread is not None or not self.available:
            return
        self._thread = threading.Thread(target=self._run, name="msgflow-ipn-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._close_all()

    def _open_for_events(self, path: Path) -> int:
        try:
            return os.open(path, O_EVTONLY)
        except OSError:
            return os.open(path, os.O_RDONLY)

    def _watch_path(self, path: Path) -> None:
        path = path.resolve()
        if path in self._registered_paths or not path.exists():
            return
        fd = self._open_for_events(path)
        flags = (
            select.KQ_NOTE_DELETE
            | select.KQ_NOTE_WRITE
            | select.KQ_NOTE_EXTEND
            | select.KQ_NOTE_ATTRIB
            | select.KQ_NOTE_LINK
            | select.KQ_NOTE_RENAME
            | select.KQ_NOTE_REVOKE
        )
        event = select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=flags)
        assert self._kqueue is not None
        self._kqueue.control([event], 0, 0)
        self._fds[fd] = path
        self._registered_paths.add(path)

    def _refresh_watches(self) -> None:
        self._watch_path(self.root_path)
        self._watch_path(self.root_path / "Library.plist")
        if not self.root_path.exists():
            return
        for app_dir in self.root_path.iterdir():
            if app_dir.is_dir():
                self._watch_path(app_dir)
        for delivered_path in self.root_path.glob("*/DeliveredNotifications.plist"):
            self._watch_path(delivered_path)

    def _run(self) -> None:
        try:
            self._kqueue = select.kqueue()
            self._refresh_watches()
            pending: set[Path] = set()
            last_event_at = 0.0
            while not self._stop_event.is_set():
                timeout = 0.2
                if pending:
                    timeout = max(0.0, self.debounce_seconds - (time.monotonic() - last_event_at))
                events = self._kqueue.control(None, 64, timeout)
                if events:
                    for event in events:
                        path = self._fds.get(event.ident)
                        if path is not None:
                            pending.add(path)
                    last_event_at = time.monotonic()
                    self._refresh_watches()
                    continue
                if pending and (time.monotonic() - last_event_at) >= self.debounce_seconds:
                    changed = set(pending)
                    pending.clear()
                    self.callback(changed)
        except Exception as e:
            logger.warning("ipn file watcher stopped: %s", e)
        finally:
            self._close_all()

    def _close_all(self) -> None:
        for fd in list(self._fds):
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()
        self._registered_paths.clear()
        if self._kqueue is not None:
            try:
                self._kqueue.close()
            except Exception:
                pass
            self._kqueue = None
