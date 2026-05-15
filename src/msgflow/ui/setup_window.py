import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSMakeRect,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSTimer

from ..common.authorization import full_disk_access_authorized
from .accessibility import accessibility_authorized, request_accessibility_authorization


class SetupWindowController(NSObject):
    WINDOW_WIDTH = 560.0
    WINDOW_HEIGHT = 430.0

    def initWithAppController_(self, app_controller):  # type: ignore[override]
        self = objc.super(SetupWindowController, self).init()
        if self is None:
            return None
        self.app_controller = app_controller
        self.window = None
        self.title_label = None
        self.subtitle_label = None
        self.accessibility_status_label = None
        self.full_disk_status_label = None
        self.accessibility_button = None
        self.full_disk_button = None
        self.continue_button = None
        self.poll_timer = None
        self._build_window()
        self.refresh_permissions()
        return self

    @objc.python_method
    def show_window(self) -> None:
        self.refresh_permissions()
        self._start_polling()
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def hide_window(self) -> None:
        self._stop_polling()
        self.window.orderOut_(None)

    @objc.python_method
    def all_permissions_granted(self) -> bool:
        return bool(accessibility_authorized() and full_disk_access_authorized())

    def refreshTimerFired_(self, _timer) -> None:
        self.refresh_permissions()

    @objc.python_method
    def refresh_permissions(self) -> None:
        accessibility_ok = accessibility_authorized()
        full_disk_ok = full_disk_access_authorized()
        self._set_permission_status(
            self.accessibility_status_label,
            self.accessibility_button,
            accessibility_ok,
        )
        self._set_permission_status(
            self.full_disk_status_label,
            self.full_disk_button,
            full_disk_ok,
        )
        self.continue_button.setEnabled_(accessibility_ok and full_disk_ok)

    def grantAccessibilityAction_(self, _sender) -> None:
        request_accessibility_authorization()
        self._start_polling()
        self.refresh_permissions()

    def grantFullDiskAccessAction_(self, _sender) -> None:
        if self.app_controller is not None:
            self.app_controller.open_full_disk_access_settings()
        self._start_polling()
        self.refresh_permissions()

    def continueAction_(self, _sender) -> None:
        self.refresh_permissions()
        if not self.all_permissions_granted():
            return
        self.hide_window()
        if self.app_controller is not None:
            self.app_controller.complete_setup()

    def windowWillClose_(self, _notification) -> None:
        self._stop_polling()

    @objc.python_method
    def _build_window(self) -> None:
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self.WINDOW_WIDTH, self.WINDOW_HEIGHT),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("msgflow Setup")
        self.window.setDelegate_(self)
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.WINDOW_WIDTH, self.WINDOW_HEIGHT))
        content.setWantsLayer_(True)
        layer = content.layer()
        if layer is not None:
            layer.setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())
        self.window.setContentView_(content)

        self.title_label = self._label(
            "Set Up msgflow",
            28,
            360,
            504,
            28,
            NSFont.boldSystemFontOfSize_(22),
            NSColor.labelColor(),
        )
        content.addSubview_(self.title_label)
        self.subtitle_label = self._label(
            "Grant these permissions, then continue. This screen updates automatically.",
            28,
            332,
            504,
            20,
            NSFont.systemFontOfSize_(13),
            NSColor.secondaryLabelColor(),
        )
        content.addSubview_(self.subtitle_label)

        self._add_permission_section(
            content,
            y=206,
            title="Accessibility",
            description="Allows msgflow to show floating actions and type or paste into other apps.",
            note="Already enabled but still not granted? Remove the old entry, then click Grant again.",
            button_title="Grant",
            action="grantAccessibilityAction:",
            status_attr="accessibility_status_label",
            button_attr="accessibility_button",
        )
        self._add_permission_section(
            content,
            y=94,
            title="Full Disk Access",
            description="Allows msgflow to read Messages and Notifications so it can monitor new items.",
            button_title="Grant",
            action="grantFullDiskAccessAction:",
            status_attr="full_disk_status_label",
            button_attr="full_disk_button",
        )

        self.continue_button = self._button("Continue", 420, 28, 112, "continueAction:")
        self.continue_button.setEnabled_(False)
        content.addSubview_(self.continue_button)

    @objc.python_method
    def _add_permission_section(
        self,
        content,
        *,
        y: float,
        title: str,
        description: str,
        button_title: str,
        action: str,
        status_attr: str,
        button_attr: str,
        note: str | None = None,
    ) -> None:
        card_height = 116.0 if note else 96.0
        card = NSView.alloc().initWithFrame_(NSMakeRect(28, y, 504, card_height))
        card.setWantsLayer_(True)
        layer = card.layer()
        if layer is not None:
            layer.setCornerRadius_(12.0)
            layer.setBackgroundColor_(NSColor.controlBackgroundColor().CGColor())
            layer.setBorderWidth_(0.5)
            layer.setBorderColor_(NSColor.separatorColor().CGColor())
        content.addSubview_(card)

        title_label = self._label(
            title,
            16,
            card_height - 36,
            250,
            22,
            NSFont.boldSystemFontOfSize_(14),
            NSColor.labelColor(),
        )
        card.addSubview_(title_label)
        description_label = self._label(
            description,
            16,
            card_height - 72,
            320,
            34,
            NSFont.systemFontOfSize_(12),
            NSColor.secondaryLabelColor(),
        )
        description_label.setLineBreakMode_(0)
        card.addSubview_(description_label)
        if note:
            note_label = self._label(
                note,
                16,
                12,
                320,
                30,
                NSFont.boldSystemFontOfSize_(11),
                NSColor.systemOrangeColor(),
            )
            note_label.setLineBreakMode_(0)
            card.addSubview_(note_label)
        status_label = self._label(
            "Checking...",
            344,
            card_height - 38,
            140,
            20,
            NSFont.systemFontOfSize_(12),
            NSColor.secondaryLabelColor(),
        )
        status_label.setAlignment_(2)
        card.addSubview_(status_label)
        button = self._button(button_title, 354, 22, 130, action)
        card.addSubview_(button)
        setattr(self, status_attr, status_label)
        setattr(self, button_attr, button)

    @objc.python_method
    def _label(self, text: str, x: float, y: float, width: float, height: float, font, color):
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        label.setStringValue_(text)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setFont_(font)
        label.setTextColor_(color)
        return label

    @objc.python_method
    def _button(self, title: str, x: float, y: float, width: float, action: str):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 30))
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        return button

    @objc.python_method
    def _set_permission_status(self, label, button, granted: bool) -> None:
        if granted:
            label.setStringValue_("Granted")
            label.setTextColor_(NSColor.systemGreenColor())
            button.setEnabled_(False)
            return
        label.setStringValue_("Needs Permission")
        label.setTextColor_(NSColor.systemOrangeColor())
        button.setEnabled_(True)

    @objc.python_method
    def _start_polling(self) -> None:
        if self.poll_timer is not None:
            return
        self.poll_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0,
            self,
            "refreshTimerFired:",
            None,
            True,
        )

    @objc.python_method
    def _stop_polling(self) -> None:
        if self.poll_timer is not None:
            self.poll_timer.invalidate()
            self.poll_timer = None
