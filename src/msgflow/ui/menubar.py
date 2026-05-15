from importlib.metadata import PackageNotFoundError, metadata, version

import objc
from AppKit import (
    NSApp,
    NSAlert,
    NSAlertSecondButtonReturn,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSWorkspace,
    NSVariableStatusItemLength,
)
from Foundation import NSObject, NSURL

from ..rpc import core_client


class MenuBarController(NSObject):
    def initWithWindowController_appController_(self, window_controller, app_controller):  # type: ignore[override]
        self = objc.super(MenuBarController, self).init()
        if self is None:
            return None
        self.window_controller = window_controller
        self.app_controller = app_controller
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self._configure_status_button()
        self.menu = NSMenu.alloc().init()
        self.menu.setDelegate_(self)
        self.status_menu_item = self._item("Status: ...", None, "circle")
        self.status_menu_item.setEnabled_(False)
        self.menu.addItem_(self.status_menu_item)
        self.menu.addItem_(NSMenuItem.separatorItem())

        self.toggle_menu_item = self._item("Start", "toggleListenerAction:", "play.circle")
        self.menu.addItem_(self.toggle_menu_item)
        self.menu.addItem_(self._item("Open Window", "openWindowAction:", "macwindow"))
        self.menu.addItem_(NSMenuItem.separatorItem())

        self.menu.addItem_(self._item("Reload Config", "reloadConfigAction:", "arrow.clockwise"))
        self.menu.addItem_(self._item("Open Config Folder", "openConfigFolderAction:", "folder"))
        self.menu.addItem_(NSMenuItem.separatorItem())

        self.accessibility_menu_item = self._item("Permissions...", "grantAccessibilityAction:", "hand.raised")
        self.menu.addItem_(self.accessibility_menu_item)
        self.launch_at_login_menu_item = self._item("Launch at Login", "toggleLaunchAtLoginAction:", "power")
        self.menu.addItem_(self.launch_at_login_menu_item)
        self.debug_menu_item = self._item("Debug Mode", "toggleDebugModeAction:", "ladybug")
        self.menu.addItem_(self.debug_menu_item)
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(self._item("About msgflow", "showAboutAction:", "info.circle"))
        self.menu.addItem_(self._item("Quit", "quitAction:", "xmark.circle"))
        self.status_item.setMenu_(self.menu)
        self.refresh_status()
        return self

    @objc.python_method
    def _configure_status_button(self) -> None:
        button = self.status_item.button()
        if button is None:
            return
        button.setTitle_("")
        image = self._symbol_image("flowchart")
        if image is not None:
            button.setImage_(image)
            if hasattr(button, "setImagePosition_"):
                button.setImagePosition_(1)

    @objc.python_method
    def _symbol_image(self, symbol_name: str):
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, symbol_name)
        if image is None:
            return None
        try:
            image.setTemplate_(True)
        except Exception:
            pass
        return image

    @objc.python_method
    def _item(self, title: str, action: str | None, symbol_name: str | None = None):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action is not None:
            item.setTarget_(self)
        if symbol_name is not None:
            image = self._symbol_image(symbol_name)
            if image is not None:
                item.setImage_(image)
        return item

    @objc.python_method
    def _refresh_menu_toggles(self) -> None:
        self.debug_menu_item.setState_(
            NSControlStateValueOn if self.app_controller.managed_core_debug_mode() else NSControlStateValueOff
        )
        self.launch_at_login_menu_item.setState_(
            NSControlStateValueOn if self.app_controller.app_launch_at_login_enabled() else NSControlStateValueOff
        )
        self.accessibility_menu_item.setHidden_(False)

    @objc.python_method
    def _apply_runtime_status(self, status_payload: dict) -> None:
        status = str(status_payload.get("status") or "unknown")
        self.status_menu_item.setTitle_(f"Status: {status}")
        self.toggle_menu_item.setTitle_("Pause" if status == "running" else "Start")
        toggle_image = self._symbol_image("pause.circle" if status == "running" else "play.circle")
        if toggle_image is not None:
            self.toggle_menu_item.setImage_(toggle_image)
        self.toggle_menu_item.setEnabled_(True)

    @objc.python_method
    def _apply_unavailable_status(self) -> None:
        self.status_menu_item.setTitle_("Status: unavailable")
        self.toggle_menu_item.setTitle_("Start")
        toggle_image = self._symbol_image("play.circle")
        if toggle_image is not None:
            self.toggle_menu_item.setImage_(toggle_image)
        self.toggle_menu_item.setEnabled_(True)

    @objc.python_method
    def _fetch_runtime_status_payload(self) -> dict | None:
        try:
            return core_client.get_status(timeout=0.3)
        except Exception:
            return None

    @objc.python_method
    def _fetch_runtime_status(self) -> str | None:
        payload = self._fetch_runtime_status_payload()
        if payload is None:
            return None
        return str(payload.get("status") or "unknown")

    @objc.python_method
    def refresh_status(self) -> None:
        self._refresh_menu_toggles()
        if not self.app_controller.setup_complete():
            self.status_menu_item.setTitle_("Status: Setup Required")
            self.toggle_menu_item.setTitle_("Continue Setup")
            toggle_image = self._symbol_image("checklist")
            if toggle_image is not None:
                self.toggle_menu_item.setImage_(toggle_image)
            self.toggle_menu_item.setEnabled_(True)
            return
        payload = self._fetch_runtime_status_payload()
        if payload is None:
            self._apply_unavailable_status()
            return
        self._apply_runtime_status(payload)

    def toggleDebugModeAction_(self, _sender) -> None:
        self.app_controller.toggle_managed_core_debug_mode()
        self.refresh_status()

    def toggleLaunchAtLoginAction_(self, _sender) -> None:
        try:
            self.app_controller.toggle_app_launch_at_login()
        except Exception as e:
            self.app_controller.show_error(str(e))
        self.refresh_status()

    def toggleListenerAction_(self, _sender) -> None:
        if not self.app_controller.setup_complete():
            self.app_controller.show_setup()
            self.refresh_status()
            return
        status = self._fetch_runtime_status()
        if status is None:
            self.app_controller.ensure_core_running(wait_timeout=0.3)
            status = self._fetch_runtime_status()
            if status is None:
                self.refresh_status()
                return
        try:
            if status == "running":
                core_client.pause_listener()
            else:
                core_client.start_listener()
        except Exception:
            self.refresh_status()
            return
        self.refresh_status()

    def grantAccessibilityAction_(self, _sender) -> None:
        self.app_controller.show_permissions()
        self.refresh_status()

    def openWindowAction_(self, _sender) -> None:
        if not self.app_controller.setup_complete():
            self.app_controller.show_setup()
            self.refresh_status()
            return
        self.app_controller.ensure_core_running()
        self.window_controller.show_window()
        self.refresh_status()

    def openConfigFolderAction_(self, _sender) -> None:
        self.app_controller.open_config_directory()

    def reloadConfigAction_(self, _sender) -> None:
        try:
            self.app_controller.restart_managed_core()
        except Exception as e:
            self.app_controller.show_error(str(e))
        self.refresh_status()

    def menuWillOpen_(self, _menu) -> None:
        self.refresh_status()

    def showAboutAction_(self, _sender) -> None:
        alert = NSAlert.alloc().init()
        github_url = self._app_project_url("GitHub") or self._app_project_url("Repository")
        info_lines = [
            f"Version: {self._app_version()}",
            f"Author: {self._app_author()}",
        ]
        if github_url:
            info_lines.append(f"GitHub: {github_url}")
        alert.setMessageText_("msgflow")
        alert.setInformativeText_("\n".join(info_lines))
        alert.addButtonWithTitle_("OK")
        if github_url:
            alert.addButtonWithTitle_("Open GitHub")
        if github_url and alert.runModal() == NSAlertSecondButtonReturn:
            url = NSURL.URLWithString_(github_url)
            if url is not None:
                NSWorkspace.sharedWorkspace().openURL_(url)
        elif not github_url:
            alert.runModal()

    @objc.python_method
    def _app_version(self) -> str:
        try:
            return version("msgflow")
        except PackageNotFoundError:
            return "unknown"

    @objc.python_method
    def _app_metadata(self):
        try:
            return metadata("msgflow")
        except PackageNotFoundError:
            return None

    @objc.python_method
    def _app_author(self) -> str:
        package_metadata = self._app_metadata()
        if package_metadata is None:
            return "Unknown"
        author = str(package_metadata.get("Author") or "").strip()
        return author or "Unknown"

    @objc.python_method
    def _app_project_url(self, label: str) -> str:
        package_metadata = self._app_metadata()
        if package_metadata is None:
            return ""
        for raw_value in package_metadata.get_all("Project-URL") or []:
            raw_label, separator, raw_url = str(raw_value).partition(",")
            if separator and raw_label.strip().lower() == label.lower():
                return raw_url.strip()
        return ""

    def quitAction_(self, _sender) -> None:
        NSApp.terminate_(None)
