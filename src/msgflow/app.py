import logging
import subprocess
import sys
import time

import objc
from AppKit import (
    NSAlert,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSEventModifierFlagCommand,
    NSEventModifierFlagOption,
    NSMenu,
    NSMenuItem,
    NSWorkspace,
)
from Foundation import NSObject, NSURL

from .ui.autostart import is_app_launch_at_login_enabled, set_app_launch_at_login
from .common.authorization import FULL_DISK_ACCESS_SETTINGS_URLS
from .rpc import core_client
from .ui.accessibility import accessibility_authorized
from .ui.floating_panel import FloatingPanelController
from .ui.main_window import MainWindowController
from .ui.menubar import MenuBarController
from .ui.notification_center import NotificationPresenter
from .ui.setup_window import SetupWindowController
from .common.logging_utils import LOG_FILE_ENV, configure_root_logging, install_unhandled_exception_logging
from .common.paths import (
    app_log_path,
    config_root_dir,
    is_frozen,
    managed_core_command,
    managed_core_environment,
    managed_core_log_path,
)
from .rpc.ui_rpc import UIRPCServer

logger = logging.getLogger(__name__)


class MacAppController(NSObject):
    def applicationDidFinishLaunching_(self, _notification) -> None:
        logger.info("app launched")
        self._managed_core_process = None
        self._managed_core_debug_mode = False
        self._setup_complete = False
        self.notification_presenter = NotificationPresenter.alloc().init()
        self.notification_presenter.request_authorization()
        self.floating_panel_controller = FloatingPanelController.alloc().initWithAppController_(self)
        self.main_window_controller = MainWindowController.alloc().init()
        self.main_window_controller.set_app_controller(self)
        self.setup_window_controller = SetupWindowController.alloc().initWithAppController_(self)
        self.menu_bar_controller = MenuBarController.alloc().initWithWindowController_appController_(
            self.main_window_controller,
            self,
        )
        self.ui_rpc_server = UIRPCServer(self)
        self.ui_rpc_server.start()
        if self.setup_window_controller.all_permissions_granted():
            self.complete_setup()
        else:
            self.show_setup()

    def applicationWillTerminate_(self, _notification) -> None:
        logger.info("app terminating")
        if getattr(self, "ui_rpc_server", None) is not None:
            self.ui_rpc_server.stop()
        self.stop_managed_core()

    @objc.python_method
    def ensure_core_running(self, wait_timeout: float = 2.0) -> bool:
        if self._core_is_available(timeout=0.2):
            return True
        process = getattr(self, "_managed_core_process", None)
        if process is None or process.poll() is not None:
            command = managed_core_command(debug=self._managed_core_debug_mode)
            env = managed_core_environment()
            if is_frozen():
                log_path = managed_core_log_path()
                log_path.parent.mkdir(parents=True, exist_ok=True)
                env[LOG_FILE_ENV] = str(log_path)
            else:
                env.pop(LOG_FILE_ENV, None)
            logger.info("starting managed core: %s", " ".join(command))
            self._managed_core_process = subprocess.Popen(
                command,
                cwd=None,
                start_new_session=True,
                env=env,
            )
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            if self._core_is_available(timeout=0.2):
                return True
            process = getattr(self, "_managed_core_process", None)
            if process is not None and process.poll() is not None:
                break
            time.sleep(0.1)
        return self._core_is_available(timeout=0.2)

    @objc.python_method
    def stop_managed_core(self) -> None:
        process = getattr(self, "_managed_core_process", None)
        if process is None:
            return
        if process.poll() is None:
            logger.info("stopping managed core")
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                logger.warning("managed core did not stop in time; killing it")
                process.kill()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        self._managed_core_process = None

    @objc.python_method
    def restart_managed_core(self, wait_timeout: float = 2.0) -> bool:
        process = getattr(self, "_managed_core_process", None)
        core_available = self._core_is_available(timeout=0.2)
        if process is None and core_available:
            raise RuntimeError("Core is not managed by msgflow-app. Please restart the external core process manually.")
        self.stop_managed_core()
        if not self.ensure_core_running(wait_timeout=wait_timeout):
            raise RuntimeError("Failed to restart msgflow-core.")
        return True

    @objc.python_method
    def managed_core_debug_mode(self) -> bool:
        return bool(self._managed_core_debug_mode)

    @objc.python_method
    def toggle_managed_core_debug_mode(self) -> bool:
        self._managed_core_debug_mode = not self._managed_core_debug_mode
        process = getattr(self, "_managed_core_process", None)
        if process is not None and process.poll() is None:
            self.stop_managed_core()
            self.ensure_core_running()
        return bool(self._managed_core_debug_mode)

    @objc.python_method
    def app_launch_at_login_enabled(self) -> bool:
        return is_app_launch_at_login_enabled()

    @objc.python_method
    def toggle_app_launch_at_login(self) -> bool:
        next_state = not is_app_launch_at_login_enabled()
        set_app_launch_at_login(next_state)
        return next_state

    @objc.python_method
    def open_config_directory(self) -> None:
        config_dir = config_root_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        url = NSURL.fileURLWithPath_(str(config_dir))
        NSWorkspace.sharedWorkspace().openURL_(url)

    @objc.python_method
    def accessibility_authorized(self) -> bool:
        return accessibility_authorized()

    @objc.python_method
    def setup_complete(self) -> bool:
        return bool(getattr(self, "_setup_complete", False))

    @objc.python_method
    def show_setup(self) -> None:
        self._setup_complete = False
        self.stop_managed_core()
        self.setup_window_controller.show_window()
        if getattr(self, "menu_bar_controller", None) is not None:
            self.menu_bar_controller.refresh_status()

    @objc.python_method
    def show_permissions(self) -> None:
        self.setup_window_controller.show_window()

    @objc.python_method
    def complete_setup(self) -> None:
        self._setup_complete = True
        self.ensure_core_running()
        if getattr(self, "menu_bar_controller", None) is not None:
            self.menu_bar_controller.refresh_status()

    @objc.python_method
    def _core_is_available(self, timeout: float = 0.5) -> bool:
        try:
            core_client.get_status(timeout=timeout)
            return True
        except Exception:
            return False

    @objc.python_method
    def show_notification(self, title: str, body: str) -> None:
        payload = {"title": title, "body": body}
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showNotificationOnMainThread:",
            payload,
            False,
        )

    @objc.python_method
    def show_floating(self, title: str, body: str, input_text: str) -> None:
        if not self.setup_complete():
            self.show_setup()
            return
        payload = {"title": title, "body": body, "input": input_text}
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showFloatingOnMainThread:",
            payload,
            False,
        )

    def showNotificationOnMainThread_(self, payload) -> None:
        self.notification_presenter.show_notification(
            str(payload.get("title") or ""),
            str(payload.get("body") or ""),
        )

    def showFloatingOnMainThread_(self, payload) -> None:
        self.floating_panel_controller.show_floating(
            str(payload.get("title") or ""),
            str(payload.get("body") or ""),
            str(payload.get("input") or ""),
        )

    @objc.python_method
    def show_error(self, text: str) -> None:
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showErrorOnMainThread:",
            str(text),
            False,
        )

    def showErrorOnMainThread_(self, text: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Error")
        alert.setInformativeText_(text)
        alert.runModal()

    @objc.python_method
    def open_full_disk_access_settings(self) -> bool:
        workspace = NSWorkspace.sharedWorkspace()
        for url_text in FULL_DISK_ACCESS_SETTINGS_URLS:
            url = NSURL.URLWithString_(url_text)
            if url is not None and workspace.openURL_(url):
                return True
        return False


@objc.python_method
def _install_main_menu(app) -> None:
    main_menu = NSMenu.alloc().init()

    app_menu_item = NSMenuItem.alloc().init()
    app_submenu = NSMenu.alloc().initWithTitle_("msgflow")
    hide_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Hide msgflow", "hide:", "h")
    hide_others_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Hide Others", "hideOtherApplications:", "h")
    hide_others_item.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand | NSEventModifierFlagOption)
    show_all_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Show All", "unhideAllApplications:", "")
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit msgflow", "terminate:", "q")
    app_submenu.addItem_(hide_item)
    app_submenu.addItem_(hide_others_item)
    app_submenu.addItem_(show_all_item)
    app_submenu.addItem_(NSMenuItem.separatorItem())
    app_submenu.addItem_(quit_item)
    app_menu_item.setSubmenu_(app_submenu)
    main_menu.addItem_(app_menu_item)

    edit_menu_item = NSMenuItem.alloc().init()
    edit_submenu = NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in [
        ("Undo", "undo:", "z"),
        ("Redo", "redo:", "Z"),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ]:
        edit_submenu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key))
    edit_menu_item.setSubmenu_(edit_submenu)
    main_menu.addItem_(edit_menu_item)

    window_menu_item = NSMenuItem.alloc().init()
    window_submenu = NSMenu.alloc().initWithTitle_("Window")
    minimize_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Minimize", "performMiniaturize:", "m")
    close_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Close Window", "performClose:", "w")
    window_submenu.addItem_(minimize_item)
    window_submenu.addItem_(close_item)
    window_menu_item.setSubmenu_(window_submenu)
    main_menu.addItem_(window_menu_item)

    app.setMainMenu_(main_menu)
    app.setWindowsMenu_(window_submenu)


def main() -> None:
    format_text = (
        ('\r\x1b[K' if sys.stderr.isatty() else '')
        + '%(asctime)s - app - %(levelname)-5s - %(message)s'
    )
    if is_frozen():
        configure_root_logging(
            level=logging.INFO,
            formatter=logging.Formatter(format_text),
            log_path=app_log_path(),
        )
    else:
        configure_root_logging(
            level=logging.INFO,
            formatter=logging.Formatter(format_text),
        )
    install_unhandled_exception_logging(logger)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    _install_main_menu(app)
    delegate = MacAppController.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__ == "__main__":
    main()
