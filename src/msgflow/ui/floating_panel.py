from math import ceil

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSMakeRect,
    NSPanel,
    NSPasteboard,
    NSPasteboardTypeString,
    NSScreen,
    NSTextField,
    NSLineBreakByWordWrapping,
    NSStringDrawingUsesLineFragmentOrigin,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import (
    NSAttributedString,
    NSMakeRange,
    NSObject,
    NSValue,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventKeyboardSetUnicodeString,
    CGEventPost,
    CGEventSetFlags,
    CGEventSourceCreate,
    kCGAnnotatedSessionEventTap,
    kCGEventFlagMaskCommand,
    kCGEventSourceStateCombinedSessionState,
)

from .accessibility import (
    HIServices,
)


from .controls import (
    FloatingTooltipController,
    hover_button_color,
    make_hover_symbol_button,
)
from .i18n import t


class FloatingPanelController(NSObject):
    FOCUS_CHECK_SECONDS = 0.2

    def init(self):  # type: ignore[override]
        return self.initWithAppController_(None)

    def initWithAppController_(self, app_controller):  # type: ignore[override]
        self = objc.super(FloatingPanelController, self).init()
        if self is None:
            return None
        self.app_controller = app_controller
        self.panel = None
        self.title_label = None
        self.body_label = None
        self.header_divider = None
        self.close_button = None
        self.type_button = None
        self.paste_button = None
        self.tooltip_controller = FloatingTooltipController.alloc().init()
        self.current_input = ""
        self.focus_timer = None
        self.local_key_monitor = None
        self.global_key_monitor = None
        self.last_focused_element = None
        return self

    @objc.python_method
    def show_floating(self, title: str, body: str, input_text: str) -> None:
        self.current_input = input_text
        panel_width, panel_height = self._measure_panel_size(title, body)
        panel_frame = self._panel_frame(panel_width, panel_height)
        if self.panel is None:
            self._create_panel(panel_frame)
        else:
            self.panel.setFrame_display_(panel_frame, True)
        self.title_label.setStringValue_(title)
        self.body_label.setStringValue_(body)
        self._layout_panel(panel_width, panel_height)
        self._update_button_help_texts()
        self.tooltip_controller.hide()
        self._install_escape_monitors()
        self.panel.orderFrontRegardless()
        self._start_focus_tracking()

    def typeAction_(self, _unused_sender) -> None:
        self._type_text(self.current_input)
        self.close_panel()

    def pasteAction_(self, _unused_sender) -> None:
        self._paste_text(self.current_input)
        self.close_panel()

    def closeAction_(self, _unused_sender) -> None:
        self.close_panel()

    def close_panel(self) -> None:
        if self.focus_timer is not None:
            self.focus_timer.invalidate()
            self.focus_timer = None
        self.last_focused_element = None
        self._remove_escape_monitors()
        self.tooltip_controller.hide()
        if self.panel is not None:
            self.panel.orderOut_(None)

    @objc.python_method
    def _start_focus_tracking(self) -> None:
        from Foundation import NSTimer

        self.last_focused_element = self._focused_text_element()
        if self.focus_timer is not None:
            self.focus_timer.invalidate()
        self.focus_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.FOCUS_CHECK_SECONDS,
            self,
            "focusTrackingTimerFired:",
            None,
            True,
        )

    def focusTrackingTimerFired_(self, _unused_timer) -> None:
        if self.panel is None or not self.panel.isVisible():
            return
        focused_element = self._focused_text_element()
        if focused_element is None or self._is_same_ax_element(
            focused_element,
            self.last_focused_element,
        ):
            return
        self.last_focused_element = focused_element
        frame = self.panel.frame()
        self.panel.setFrame_display_(self._panel_frame(frame.size.width, frame.size.height), True)

    @objc.python_method
    def _create_panel(self, frame) -> None:
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setFloatingPanel_(True)
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setMovable_(True)
        self.panel.setMovableByWindowBackground_(True)
        content_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, frame.size.height))
        content_view.setWantsLayer_(True)
        content_layer = content_view.layer()
        if content_layer is not None:
            content_layer.setCornerRadius_(18.0)
            # Keep panel corners rounded, but do not clip child button shadows.
            content_layer.setMasksToBounds_(False)
            content_layer.setBackgroundColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.972, 0.925).CGColor()
            )
            content_layer.setBorderWidth_(0.55)
            content_layer.setBorderColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.79, 0.58).CGColor()
            )
            # Keep a subtle edge and a tighter shadow so the panel reads clearly
            # without turning into a heavy standalone card.
            content_layer.setShadowColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.15).CGColor()
            )
            content_layer.setShadowOpacity_(1.0)
            content_layer.setShadowRadius_(15.0)
            content_layer.setShadowOffset_((0.0, -2.8))
        self.panel.setContentView_(content_view)

        self.title_label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
        self.title_label.setBezeled_(False)
        self.title_label.setDrawsBackground_(False)
        self.title_label.setEditable_(False)
        self.title_label.setSelectable_(False)
        self.title_label.setFont_(NSFont.boldSystemFontOfSize_(15))
        self.title_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.18, 1.0))
        content_view.addSubview_(self.title_label)

        self.body_label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
        self.body_label.setBezeled_(False)
        self.body_label.setDrawsBackground_(False)
        self.body_label.setEditable_(False)
        self.body_label.setSelectable_(False)
        self.body_label.setFont_(NSFont.systemFontOfSize_(12))
        self.body_label.setLineBreakMode_(NSLineBreakByWordWrapping)
        self.body_label.setUsesSingleLineMode_(False)
        self.body_label.setAllowsDefaultTighteningForTruncation_(False)
        body_cell = self.body_label.cell()
        if body_cell is not None:
            body_cell.setWraps_(True)
            body_cell.setLineBreakMode_(NSLineBreakByWordWrapping)
        self.body_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.40, 1.0))
        content_view.addSubview_(self.body_label)

        self.header_divider = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        self.header_divider.setWantsLayer_(True)
        divider_layer = self.header_divider.layer()
        if divider_layer is not None:
            divider_layer.setBackgroundColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.78, 0.82).CGColor()
            )
        content_view.addSubview_(self.header_divider)

        self.type_button = make_hover_symbol_button(
            t("action.type"), 0, 0, 40, 27, self, "typeAction:", "keyboard", t("action.type"),
            hover_color=hover_button_color("blue"),
            tooltip_controller=self.tooltip_controller,
            symbol_size=18.0,
            icon_inset_x=6.0,
            icon_inset_y=3.0,
        )
        content_view.addSubview_(self.type_button)

        self.paste_button = make_hover_symbol_button(
            t("action.paste"), 0, 0, 40, 27, self, "pasteAction:", "doc.on.doc", t("action.paste"),
            hover_color=hover_button_color("green"),
            tooltip_controller=self.tooltip_controller,
            symbol_size=18.0,
            icon_inset_x=6.0,
            icon_inset_y=4.5,
        )
        content_view.addSubview_(self.paste_button)

        self.close_button = make_hover_symbol_button(
            t("action.close"), 0, 0, 40, 27, self, "closeAction:", "xmark", t("action.close"),
            hover_color=hover_button_color("red"),
            tooltip_controller=self.tooltip_controller,
            symbol_size=16.0,
            icon_inset_x=8.0,
            icon_inset_y=5.0,
        )
        content_view.addSubview_(self.close_button)
        self._layout_panel(frame.size.width, frame.size.height)

    @objc.python_method
    def _layout_panel(self, width: float, height: float) -> None:
        if self.panel is None:
            return
        content_view = self.panel.contentView()
        if content_view is not None:
            content_view.setFrame_(NSMakeRect(0, 0, width, height))
        metrics = self._panel_metrics()
        horizontal_padding = metrics["horizontal_padding"]
        top_padding = metrics["top_padding"]
        bottom_padding = metrics["bottom_padding"]
        button_gap = metrics["button_gap"]
        title_height = metrics["title_height"]
        button_width = metrics["button_width"]
        button_height = metrics["button_height"]
        title_y = height - top_padding - title_height - metrics["title_top_offset"]
        icon_button_y = height - top_padding - button_height + metrics["button_top_offset"]
        type_button_x = horizontal_padding
        paste_button_x = type_button_x + button_width + button_gap
        close_button_x = paste_button_x + button_width + button_gap
        divider_x = close_button_x + button_width + metrics["divider_gap"]
        title_left = divider_x + metrics["title_left_gap"]
        self.type_button.setFrame_(
            NSMakeRect(
                type_button_x,
                icon_button_y,
                button_width,
                button_height,
            )
        )
        self.paste_button.setFrame_(
            NSMakeRect(
                paste_button_x,
                icon_button_y,
                button_width,
                button_height,
            )
        )
        self.close_button.setFrame_(
            NSMakeRect(
                close_button_x,
                icon_button_y,
                button_width,
                button_height,
            )
        )
        divider_height = button_height - 1.0
        self.header_divider.setFrame_(
            NSMakeRect(
                divider_x,
                icon_button_y + 0.5,
                1.0,
                divider_height,
            )
        )
        self.title_label.setFrame_(
            NSMakeRect(
                title_left,
                title_y,
                width - title_left - horizontal_padding,
                title_height,
            )
        )
        body_bottom = bottom_padding
        body_top = min(icon_button_y, title_y) - metrics["title_body_gap"]
        body_height = max(0.0, body_top - body_bottom)
        self.body_label.setFrame_(
            NSMakeRect(
                horizontal_padding,
                body_bottom,
                width - horizontal_padding * 2,
                body_height,
            )
        )

    @objc.python_method
    def _install_escape_monitors(self) -> None:
        if self.local_key_monitor is None:
            self.local_key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown,
                self._handle_local_key_event,
            )
        if self.global_key_monitor is None:
            self.global_key_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown,
                self._handle_global_key_event,
            )

    @objc.python_method
    def _remove_escape_monitors(self) -> None:
        if self.local_key_monitor is not None:
            NSEvent.removeMonitor_(self.local_key_monitor)
            self.local_key_monitor = None
        if self.global_key_monitor is not None:
            NSEvent.removeMonitor_(self.global_key_monitor)
            self.global_key_monitor = None

    @objc.python_method
    def _should_close_for_event(self, event) -> bool:
        return bool(
            self.panel is not None
            and self.panel.isVisible()
            and event is not None
            and int(event.keyCode()) == 53
        )

    @objc.python_method
    def _handle_local_key_event(self, event):
        if self._should_close_for_event(event):
            self.close_panel()
            return None
        return event

    @objc.python_method
    def _handle_global_key_event(self, event) -> None:
        if self._should_close_for_event(event):
            self.close_panel()

    @objc.python_method
    def _panel_metrics(self):
        return {
            "horizontal_padding": 14.0,
            "top_padding": 14.0,
            "bottom_padding": 12.0,
            "button_gap": 7.0,
            "button_width": 40.0,
            "button_height": 27.0,
            "divider_gap": 12.0,
            "title_left_gap": 8.0,
            "title_height": 24.0,
            "title_top_offset": 2.0,
            "button_top_offset": 2.5,
            "title_body_gap": 8.0,
            "panel_margin": 12.0,
            "min_width": 320.0,
            "max_width": 640.0,
        }

    @objc.python_method
    def _measure_panel_size(self, title: str, body: str):
        panel_width = self._measure_panel_width(title, body)
        panel_height = self._measure_panel_height(body, panel_width)
        return panel_width, panel_height

    @objc.python_method
    def _measure_panel_width(self, title: str, body: str) -> float:
        metrics = self._panel_metrics()
        min_width = metrics["min_width"]
        max_width = metrics["max_width"]
        visible_frame = self._anchor_visible_frame()
        if visible_frame is not None:
            max_width = min(
                max_width,
                max(min_width, visible_frame.size.width - metrics["panel_margin"] * 2.0),
            )
        title_left = self._title_left(metrics)
        title_width = self._single_line_text_width(
            title,
            NSFont.boldSystemFontOfSize_(15),
        )
        title_required_width = title_left + title_width + metrics["horizontal_padding"]
        body_line_width = max(
            (
                self._single_line_text_width(line, NSFont.systemFontOfSize_(12))
                for line in (body.splitlines() or [""])
            ),
            default=0.0,
        )
        body_required_width = body_line_width + metrics["horizontal_padding"] * 2.0
        preferred_width = max(min_width, title_required_width, body_required_width)
        return float(min(max_width, preferred_width))

    @objc.python_method
    def _measure_panel_height(self, body: str, panel_width: float) -> float:
        metrics = self._panel_metrics()
        body_width = max(1.0, panel_width - metrics["horizontal_padding"] * 2.0)
        body_height = self._wrapped_text_height(
            body,
            NSFont.systemFontOfSize_(12),
            body_width,
        )
        return float(self._panel_chrome_height(metrics) + body_height)

    @objc.python_method
    def _panel_chrome_height(self, metrics) -> float:
        return float(
            metrics["top_padding"]
            + metrics["title_height"]
            + metrics["title_top_offset"]
            + metrics["title_body_gap"]
            + metrics["bottom_padding"]
        )

    @objc.python_method
    def _title_left(self, metrics) -> float:
        return float(
            metrics["horizontal_padding"]
            + metrics["button_width"] * 3.0
            + metrics["button_gap"] * 2.0
            + metrics["divider_gap"]
            + metrics["title_left_gap"]
        )

    @objc.python_method
    def _single_line_text_width(self, text: str, font) -> float:
        if not text:
            return 0.0
        attributed = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: font},
        )
        return float(ceil(attributed.size().width))

    @objc.python_method
    def _wrapped_text_height(self, text: str, font, width: float) -> float:
        if not text:
            return 0.0
        attributed = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: font},
        )
        bounds = attributed.boundingRectWithSize_options_context_(
            (width, 100000.0),
            NSStringDrawingUsesLineFragmentOrigin,
            None,
        )
        return float(ceil(bounds.size.height))

    @objc.python_method
    def _anchor_visible_frame(self):
        caret_rect = self._focused_text_caret_rect()
        if caret_rect is not None:
            screen = self._screen_for_point(caret_rect.origin.x, caret_rect.origin.y)
        else:
            mouse_location = NSEvent.mouseLocation()
            screen = self._screen_for_point(mouse_location.x, mouse_location.y)
        if screen is None:
            return None
        return screen.visibleFrame()

    @objc.python_method
    def _update_button_help_texts(self) -> None:
        preview_text = " ".join(
            line.strip() for line in self.current_input.splitlines() if line.strip()
        )
        quoted_preview = f'"{preview_text}"' if preview_text else ""
        type_text = f"{t('action.type')} {quoted_preview}".strip()
        paste_text = f"{t('action.paste')} {quoted_preview}".strip()
        if self.type_button is not None:
            self.type_button.set_hover_text(type_text)
        if self.paste_button is not None:
            self.paste_button.set_hover_text(paste_text)
        if self.close_button is not None:
            self.close_button.set_hover_text(t("action.close"))

    @objc.python_method
    def _panel_frame(self, width: float, height: float):
        caret_rect = self._focused_text_caret_rect()
        if caret_rect is not None:
            x = caret_rect.origin.x + caret_rect.size.width + 12
            y = caret_rect.origin.y - height - 12
            anchor_x = caret_rect.origin.x
            anchor_y = caret_rect.origin.y
        else:
            mouse_location = NSEvent.mouseLocation()
            x = mouse_location.x + 12
            y = mouse_location.y - height - 12
            anchor_x = mouse_location.x
            anchor_y = mouse_location.y
        screen = self._screen_for_point(anchor_x, anchor_y)
        visible_frame = screen.visibleFrame() if screen is not None else None
        if visible_frame is not None:
            min_x = visible_frame.origin.x + 12
            min_y = visible_frame.origin.y + 12
            max_x = visible_frame.origin.x + visible_frame.size.width - width - 12
            max_y = visible_frame.origin.y + visible_frame.size.height - height - 12
            x = min(max(x, min_x), max_x if max_x >= min_x else min_x)
            y = min(max(y, min_y), max_y if max_y >= min_y else min_y)
        else:
            if x < 12:
                x = 12
            if y < 12:
                y = 12
        return NSMakeRect(x, y, width, height)

    @objc.python_method
    def _focused_text_caret_rect(self):
        focused_element = self._focused_text_element()
        if focused_element is None:
            return None
        try:
            error, selected_range = HIServices.AXUIElementCopyAttributeValue(
                focused_element,
                "AXSelectedTextRange",
                None,
            )
            if error != getattr(HIServices, "kAXErrorSuccess", 0) or selected_range is None:
                return None
            caret_range = self._collapsed_range_value(selected_range)
            if caret_range is None:
                return None
            error, bounds_value = HIServices.AXUIElementCopyParameterizedAttributeValue(
                focused_element,
                "AXBoundsForRange",
                caret_range,
                None,
            )
            if error != getattr(HIServices, "kAXErrorSuccess", 0) or bounds_value is None:
                return None
            return self._ax_rect_to_appkit_rect(bounds_value)
        except Exception:
            return None

    @objc.python_method
    def _focused_text_element(self):
        if HIServices is None:
            return None
        try:
            system_wide = HIServices.AXUIElementCreateSystemWide()
            error, focused_element = HIServices.AXUIElementCopyAttributeValue(
                system_wide,
                "AXFocusedUIElement",
                None,
            )
            if error != getattr(HIServices, "kAXErrorSuccess", 0) or focused_element is None:
                return None
            return focused_element
        except Exception:
            return None

    @objc.python_method
    def _is_same_ax_element(self, left, right) -> bool:
        if left is None or right is None:
            return left is right
        try:
            return bool(left.isEqual_(right))
        except Exception:
            return left == right

    @objc.python_method
    def _collapsed_range_value(self, range_value):
        try:
            selected_range = range_value.rangeValue()
        except Exception:
            return range_value
        caret_location = int(selected_range.location) + int(selected_range.length)
        return NSValue.valueWithRange_(NSMakeRange(caret_location, 0))

    @objc.python_method
    def _ax_rect_to_appkit_rect(self, bounds_value):
        try:
            rect = bounds_value.rectValue()
        except Exception:
            try:
                rect = bounds_value.CGRectValue()
            except Exception:
                rect = bounds_value
        if not hasattr(rect, "origin") or not hasattr(rect, "size"):
            return None
        max_y = self._desktop_max_y()
        appkit_y = max_y - rect.origin.y - rect.size.height
        return NSMakeRect(rect.origin.x, appkit_y, rect.size.width, rect.size.height)

    @objc.python_method
    def _desktop_max_y(self) -> float:
        screens = NSScreen.screens()
        if not screens:
            return 0.0
        return max(screen.frame().origin.y + screen.frame().size.height for screen in screens)

    @objc.python_method
    def _screen_for_point(self, x: float, y: float):
        for screen in NSScreen.screens():
            frame = screen.frame()
            if (
                x >= frame.origin.x
                and x <= frame.origin.x + frame.size.width
                and y >= frame.origin.y
                and y <= frame.origin.y + frame.size.height
            ):
                return screen
        screens = NSScreen.screens()
        if screens:
            return screens[0]
        return None

    @objc.python_method
    def _event_source(self):
        return CGEventSourceCreate(kCGEventSourceStateCombinedSessionState)

    @objc.python_method
    def _type_text(self, text: str) -> None:
        source = self._event_source()
        key_down = CGEventCreateKeyboardEvent(source, 0, True)
        CGEventKeyboardSetUnicodeString(key_down, len(text), text)
        CGEventPost(kCGAnnotatedSessionEventTap, key_down)
        key_up = CGEventCreateKeyboardEvent(source, 0, False)
        CGEventKeyboardSetUnicodeString(key_up, len(text), text)
        CGEventPost(kCGAnnotatedSessionEventTap, key_up)

    @objc.python_method
    def _paste_text(self, text: str) -> None:
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)
        source = self._event_source()
        key_down = CGEventCreateKeyboardEvent(source, 9, True)
        CGEventSetFlags(key_down, kCGEventFlagMaskCommand)
        CGEventPost(kCGAnnotatedSessionEventTap, key_down)
        key_up = CGEventCreateKeyboardEvent(source, 9, False)
        CGEventSetFlags(key_up, kCGEventFlagMaskCommand)
        CGEventPost(kCGAnnotatedSessionEventTap, key_up)
