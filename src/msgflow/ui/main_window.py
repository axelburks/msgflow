import json
import re
from typing import Any, Optional

import objc
from AppKit import (
    NSAlert,
    NSApp,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBox,
    NSButton,
    NSControlSizeRegular,
    NSColor,
    NSEventModifierFlagCommand,
    NSFocusRingTypeNone,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageView,
    NSEvent,
    NSMakePoint,
    NSMakeRect,
    NSMomentaryChangeButton,
    NSPopUpButton,
    NSScrollView,
    NSScreen,
    NSTableColumn,
    NSTableCellView,
    NSTableView,
    NSTextField,
    NSTextFieldCell,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSView,
    NSViewBoundsDidChangeNotification,
    NSViewHeightSizable,
    NSViewMinYMargin,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
    NSWorkspace,
)
from Foundation import NSAttributedString, NSObject, NSNotificationCenter, NSURL
from WebKit import WKWebView, WKWebViewConfiguration

from ..common.record_query import FIELD_MAP, parse_query
from ..common.run_models import MESSAGE_KINDS, RunQueryFilters, RUN_STATUSES, RUN_TRIGGER_TYPES
from ..rpc import core_client
from ..common.paths import assets_dir
from .controls import (
    FloatingTooltipController,
    hover_button_color,
    hover_symbol_button_width,
    make_hover_symbol_button,
)


class AppCommandWebView(WKWebView):
    def performKeyEquivalent_(self, event):  # type: ignore[override]
        characters = str(event.charactersIgnoringModifiers() or "").lower()
        has_command = bool(int(event.modifierFlags()) & int(NSEventModifierFlagCommand))
        if has_command and characters == "q":
            NSApp.terminate_(None)
            return True
        return objc.super(AppCommandWebView, self).performKeyEquivalent_(event)


class PanelBorderOverlay(NSView):
    def hitTest_(self, _point):  # type: ignore[override]
        return None


QUERY_HELP_TEXT = (
    "About\n"
    "  Filter the run-record list with a query DSL.\n"
    "  Bare words search the `text` field. Field clauses use `field:value`.\n"
    "  Spaces mean AND; use parentheses to group conditions.\n"
    "\n"
    "Boolean logic\n"
    "  a b  -  a AND b\n"
    "  a | b, a OR b  -  a OR b\n"
    "  -a, !a, NOT a  -  exclude a\n"
    "  kind:sms (status:failed | status:success)  -  grouped logic\n"
    "\n"
    "Field operators\n"
    "  text:hello  -  contains hello\n"
    "  text:=hello  -  exact equals hello\n"
    "  text:~hello.*  -  regex match\n"
    "  text:!hello  -  does not contain hello\n"
    "  text:!=hello  -  not equals hello\n"
    "  text:!~^debug  -  regex does not match\n"
    "\n"
    "Field groups\n"
    "  status:(failed | success)  -  same as status:failed OR status:success\n"
    "  text:(\"hello world\" | 验证码)  -  OR values in the same field\n"
    "  status:(=failed | !=success | !~debug)  -  operator shorthand\n"
    "\n"
    "Quotes and escaping\n"
    "  Quote spaces or DSL symbols: text:\"a | b\", text:'hello (test)'\n"
    "  Bare values use \\ to escape one char: alice\\ bob, a\\|b\n"
    "  Quote regex for readability: code:~'\\d+', text:~'(验证码|code)\\d{6}'\n"
    "\n"
    "Available fields (all operators above supported)\n"
    "  " + ", ".join(FIELD_MAP.keys()) + "\n"
    "\n"
    "Examples\n"
    "  hello  -  search hello in text\n"
    "  sender:+86 status:failed  -  sender has +86 AND run failed\n"
    "  kind:sms -(sender:bot | text:debug)  -  sms excluding bot/debug\n"
    "  trigger:!auto code:~'\\d{6}'  -  non-auto runs with a 6-digit code\n"
    "  trace:'\"dest\":\"bark_axel\"'  -  trace json mentions dest bark_axel\n"
    "  msg:!~^debug kind:sms  -  sms whose msg does NOT start with debug"
)


class PaddedTextFieldCell(NSTextFieldCell):
    LEFT_PADDING = 8.0
    RIGHT_PADDING = 24.0

    @objc.python_method
    def _vertically_centered(self, rect):
        cell_size = self.cellSizeForBounds_(rect)
        text_height = min(rect.size.height, cell_size.height)
        y = rect.origin.y + max(0.0, (rect.size.height - text_height) / 2.0)
        return NSMakeRect(rect.origin.x, y, rect.size.width, text_height)

    @objc.python_method
    def _padded(self, rect):
        horizontal_padding = self.LEFT_PADDING + self.RIGHT_PADDING
        new_width = max(0.0, rect.size.width - horizontal_padding)
        return NSMakeRect(rect.origin.x + self.LEFT_PADDING, rect.origin.y, new_width, rect.size.height)

    def drawingRectForBounds_(self, rect):  # type: ignore[override]
        base = objc.super(PaddedTextFieldCell, self).drawingRectForBounds_(rect)
        return self._padded(self._vertically_centered(base))

    def titleRectForBounds_(self, rect):  # type: ignore[override]
        base = objc.super(PaddedTextFieldCell, self).titleRectForBounds_(rect)
        return self._padded(self._vertically_centered(base))

    def editWithFrame_inView_editor_delegate_event_(self, rect, controlView, textObj, delegate, event):  # type: ignore[override]
        edit_rect = self._padded(self._vertically_centered(rect))
        objc.super(PaddedTextFieldCell, self).editWithFrame_inView_editor_delegate_event_(
            edit_rect, controlView, textObj, delegate, event
        )

    def selectWithFrame_inView_editor_delegate_start_length_(self, rect, controlView, textObj, delegate, start, length):  # type: ignore[override]
        select_rect = self._padded(self._vertically_centered(rect))
        objc.super(PaddedTextFieldCell, self).selectWithFrame_inView_editor_delegate_start_length_(
            select_rect, controlView, textObj, delegate, start, length
        )


class QueryHelpIconView(NSImageView):
    def initWithFrame_(self, frame):  # type: ignore[override]
        self = objc.super(QueryHelpIconView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._tracking_area = None
        self._hover_target = None
        return self

    @objc.python_method
    def set_hover_target(self, target) -> None:
        self._hover_target = target

    def updateTrackingAreas(self) -> None:
        if self._tracking_area is not None:
            self.removeTrackingArea_(self._tracking_area)
        options = (
            NSTrackingMouseEnteredAndExited
            | NSTrackingActiveAlways
            | NSTrackingInVisibleRect
        )
        self._tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            options,
            self,
            None,
        )
        self.addTrackingArea_(self._tracking_area)
        objc.super(QueryHelpIconView, self).updateTrackingAreas()

    def mouseEntered_(self, _event) -> None:
        if self._hover_target is not None and hasattr(self._hover_target, "_show_query_help_tooltip"):
            self._hover_target._show_query_help_tooltip()

    def mouseExited_(self, _event) -> None:
        if self._hover_target is not None and hasattr(self._hover_target, "_hide_query_help_tooltip"):
            self._hover_target._hide_query_help_tooltip()


class FilterSegmentedControl(NSView):
    def initWithFrame_(self, frame):  # type: ignore[override]
        self = objc.super(FilterSegmentedControl, self).initWithFrame_(frame)
        if self is None:
            return None
        self._buttons = []
        self._labels = []
        self._selected_segment = 0
        self._target = None
        self._action = None
        self._font = NSFont.systemFontOfSize_(12.0)
        return self

    def setSegmentCount_(self, count):  # type: ignore[override]
        for button in self._buttons:
            button.removeFromSuperview()
        self._buttons = []
        self._labels = ["" for _ in range(int(count))]
        for index in range(int(count)):
            button = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
            button.setBordered_(False)
            button.setButtonType_(NSMomentaryChangeButton)
            button.setTag_(index)
            button.setTarget_(self)
            button.setAction_("segmentButtonClicked:")
            button.setFont_(self._font)
            self.addSubview_(button)
            self._buttons.append(button)
        self._layout_buttons()
        self._refresh_buttons()

    def setLabel_forSegment_(self, label, segment):  # type: ignore[override]
        index = int(segment)
        if 0 <= index < len(self._labels):
            self._labels[index] = str(label)
            self._buttons[index].setTitle_(str(label))
            self._refresh_buttons()

    def setSelectedSegment_(self, segment):  # type: ignore[override]
        self._selected_segment = int(segment)
        self._refresh_buttons()

    def selectedSegment(self):  # type: ignore[override]
        return int(self._selected_segment)

    def setTarget_(self, target):  # type: ignore[override]
        self._target = target

    def setAction_(self, action):  # type: ignore[override]
        self._action = str(action)

    def setFont_(self, font):  # type: ignore[override]
        self._font = font
        for button in self._buttons:
            button.setFont_(font)

    def setFrame_(self, frame) -> None:  # type: ignore[override]
        objc.super(FilterSegmentedControl, self).setFrame_(frame)
        self._layout_buttons()
        self.setNeedsDisplay_(True)

    def segmentButtonClicked_(self, sender) -> None:
        self.setSelectedSegment_(int(sender.tag()))
        if self._target is None or not self._action:
            return
        method_name = self._action.replace(":", "_")
        callback = getattr(self._target, method_name, None)
        if callable(callback):
            callback(self)

    def drawRect_(self, _dirty_rect) -> None:  # type: ignore[override]
        bounds = self.bounds()
        if bounds.size.width <= 0 or bounds.size.height <= 0:
            return
        outer = NSMakeRect(0.5, 0.5, bounds.size.width - 1.0, bounds.size.height - 1.0)
        outer_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(outer, 5.0, 5.0)
        NSColor.colorWithCalibratedWhite_alpha_(0.92, 1.0).setFill()
        outer_path.fill()
        count = len(self._buttons)
        if count > 0:
            segment_width = bounds.size.width / count
            selected_x = segment_width * max(0, min(self._selected_segment, count - 1))
            selected = NSMakeRect(selected_x + 1.0, 1.0, segment_width - 2.0, bounds.size.height - 2.0)
            selected_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(selected, 5.0, 5.0)
            accent = NSColor.controlAccentColor() if hasattr(NSColor, "controlAccentColor") else NSColor.systemBlueColor()
            accent.setFill()
            selected_path.fill()
            NSColor.colorWithCalibratedWhite_alpha_(0.72, 0.42).setStroke()
            for index in range(1, count):
                x = segment_width * index
                line = NSBezierPath.bezierPath()
                line.moveToPoint_((x, 4.0))
                line.lineToPoint_((x, bounds.size.height - 4.0))
                line.stroke()

    @objc.python_method
    def _layout_buttons(self) -> None:
        count = len(self._buttons)
        if count <= 0:
            return
        bounds = self.bounds()
        width = bounds.size.width / count
        for index, button in enumerate(self._buttons):
            button.setFrame_(NSMakeRect(width * index, 0, width, bounds.size.height))

    @objc.python_method
    def _refresh_buttons(self) -> None:
        for index, button in enumerate(self._buttons):
            selected = index == self._selected_segment
            title = NSAttributedString.alloc().initWithString_attributes_(
                self._labels[index],
                {
                    NSFontAttributeName: self._font,
                    NSForegroundColorAttributeName: NSColor.whiteColor() if selected else NSColor.labelColor(),
                },
            )
            button.setAttributedTitle_(title)
        self.setNeedsDisplay_(True)


class MainWindowController(NSObject):
    PAGE_SIZE = 50
    WINDOW_WIDTH = 1320.0
    WINDOW_HEIGHT = 780.0
    CONFIG_WINDOW_WIDTH = 920.0
    CONFIG_WINDOW_HEIGHT = 680.0
    CONFIG_WINDOW_PADDING = 16.0
    TOP_MARGIN = 14.0
    CONTROL_HEIGHT = 28.0
    CONTROL_FONT_SIZE = 12.0
    ACTION_TO_FILTER_GAP = 12.0
    FILTER_TO_LIST_GAP = 10.0
    CONTENT_BOTTOM = 20.0
    LEFT_PANEL_X = 20.0
    LEFT_PANEL_WIDTH = 580.0
    DETAIL_GAP = 20.0
    FILTER_REFRESH_WIDTH = 28.0
    FILTER_KIND_WIDTH = 220.0
    FILTER_TRIGGER_WIDTH = 120.0
    FILTER_STATUS_WIDTH = 120.0
    FILTER_CLEAR_WIDTH = 28.0
    FILTER_HELP_WIDTH = 20.0
    FILTER_GAP = 10.0
    ACTION_ICON_WIDTH = 32.0
    ACTION_BUTTON_GAP = 8.0
    ACTION_GROUP_GAP = 16.0
    PANEL_CORNER_RADIUS = 5.0
    PANEL_BORDER_WIDTH = 0.65
    PANEL_CONTENT_INSET = 1.0
    ACTION_BUTTON_SPECS = {
        "rematch_button": ("Rematch", "rematchAction:", "arrow.trianglehead.swap", "Rematch selected message and send it again", "purple", 112.0, ACTION_BUTTON_GAP),
        "resend_button": ("Resend", "resendAction:", "paperplane", "Resend the selected run to one destination", "green", 104.0, ACTION_BUTTON_GAP),
        "delete_button": ("Delete", "deleteAction:", "trash", "Delete the selected run record", "red", 96.0, ACTION_GROUP_GAP),
        "cursor_button": ("Cursor", "editCursorAction:", "arrow.up.to.line.circle", "Edit per-kind destination cursors", "blue", 96.0, ACTION_BUTTON_GAP),
        "config_button": ("Config", "showConfigAction:", "gearshape", "View the effective built config", "neutral", 96.0, 0.0),
    }
    AUTO_LOAD_THRESHOLD = 120.0
    TAG_LINE1_LEFT = 101
    TAG_LINE1_MIDDLE = 102
    TAG_LINE1_RIGHT = 103
    TAG_LINE2 = 104
    TAG_LINE3 = 105
    TAG_LINE4_LEFT = 106
    TAG_LINE4_MIDDLE = 107
    TAG_LINE4_RIGHT = 108
    DEFAULT_COLLAPSED_DETAIL_PATHS = (("message", "msg"), ("all_runs",))

    def init(self):  # type: ignore[override]
        self = objc.super(MainWindowController, self).init()
        if self is None:
            return None
        self.app_controller = None
        self.window = None
        self.table_view = None
        self.list_panel = None
        self.list_border_overlay = None
        self.detail_panel = None
        self.detail_border_overlay = None
        self.detail_web_view = None
        self.list_scroll = None
        self.kind_tabs = None
        self.refresh_button = None
        self.cursor_button = None
        self.rematch_button = None
        self.resend_button = None
        self.delete_button = None
        self.config_button = None
        self.config_window = None
        self.config_web_view = None
        self.config_reload_button = None
        self.trigger_popup = None
        self.status_popup = None
        self.query_field = None
        self.query_help_icon = None
        self.query_help_tooltip = None
        self.query_error_tooltip = None
        self.button_tooltip = None
        self._query_field_error = False
        self.clear_filters_button = None
        self.run_items: list[dict[str, Any]] = []
        self.total_count = 0
        self.selected_row = -1
        self.selected_message_detail: Optional[dict[str, Any]] = None
        self.kind_filter = None
        self._is_loading_more = False
        self._resend_sheet_popup = None
        self._resend_sheet_options: list[tuple[str, str]] = []
        self._cursor_sheet_rows: list[tuple[str, str, Any]] = []
        self._jsoneditor_js_source = self._load_svelte_jsoneditor_js_for_inline_script()
        self._jsoneditor_base_url = NSURL.fileURLWithPath_isDirectory_(str(assets_dir()), True)
        self._build_window()
        return self

    @objc.python_method
    def set_app_controller(self, app_controller) -> None:
        self.app_controller = app_controller

    @objc.python_method
    def show_window(self) -> None:
        self.refresh_data()
        self._move_window_to_current_screen()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _move_window_to_current_screen(self) -> None:
        if self.window is None:
            return
        self._move_window_to_current_screen_(self.window)

    @objc.python_method
    def _move_config_window_to_current_screen(self) -> None:
        if self.config_window is None:
            return
        self._move_window_to_current_screen_(self.config_window)

    @objc.python_method
    def _move_window_to_current_screen_(self, window) -> None:
        screen = self._screen_at_mouse_location()
        if screen is None:
            screen = window.screen() or NSScreen.mainScreen()
        if screen is None:
            return
        visible_frame = screen.visibleFrame()
        frame = window.frame()
        origin_x = visible_frame.origin.x + max(0.0, (visible_frame.size.width - frame.size.width) / 2.0)
        origin_y = visible_frame.origin.y + max(0.0, (visible_frame.size.height - frame.size.height) / 2.0)
        window.setFrameOrigin_(NSMakePoint(origin_x, origin_y))

    @objc.python_method
    def _screen_at_mouse_location(self):
        point = NSEvent.mouseLocation()
        for screen in NSScreen.screens():
            frame = screen.frame()
            in_x = frame.origin.x <= point.x < frame.origin.x + frame.size.width
            in_y = frame.origin.y <= point.y < frame.origin.y + frame.size.height
            if in_x and in_y:
                return screen
        return None

    @objc.python_method
    def _build_window(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(80, 80, self.WINDOW_WIDTH, self.WINDOW_HEIGHT),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("msgflow")
        self.window.setDelegate_(self)
        self.window.setReleasedWhenClosed_(False)

        content = self.window.contentView()
        content.setWantsLayer_(True)
        content_layer = content.layer()
        if content_layer is not None:
            content_layer.setBackgroundColor_(NSColor.whiteColor().CGColor())

        action_y = self._action_row_y_for_height_(content.bounds().size.height)
        filter_y = self._filter_row_y_for_height_(content.bounds().size.height)
        self.button_tooltip = FloatingTooltipController.alloc().init()
        filter_layout = self._filter_layout_for_content_bounds(content.bounds())
        self.refresh_button = self._symbol_button(
            "Refresh",
            filter_layout["refresh_x"],
            filter_y,
            self.FILTER_REFRESH_WIDTH,
            "refreshAction:",
            "arrow.clockwise",
            "Refresh records",
        )
        self.kind_tabs = FilterSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(filter_layout["kind_x"], filter_y, self.FILTER_KIND_WIDTH, self.CONTROL_HEIGHT)
        )
        self.kind_tabs.setSegmentCount_(3)
        self.kind_tabs.setLabel_forSegment_("All", 0)
        self.kind_tabs.setLabel_forSegment_("SMS", 1)
        self.kind_tabs.setLabel_forSegment_("Notify", 2)
        self.kind_tabs.setSelectedSegment_(0)
        self.kind_tabs.setTarget_(self)
        self.kind_tabs.setAction_("kindFilterChanged:")
        self.kind_tabs.setAutoresizingMask_(NSViewMinYMargin)
        self._style_filter_segmented_control(self.kind_tabs)

        for attr in self.ACTION_BUTTON_SPECS:
            setattr(self, attr, self._action_symbol_button(attr, action_y))
        self._layout_action_buttons(content.bounds())
        content.addSubview_(self.kind_tabs)
        content.addSubview_(self.refresh_button)
        content.addSubview_(self.cursor_button)
        content.addSubview_(self.rematch_button)
        content.addSubview_(self.resend_button)
        content.addSubview_(self.delete_button)
        content.addSubview_(self.config_button)

        self.trigger_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(filter_layout["trigger_x"], filter_y, self.FILTER_TRIGGER_WIDTH, self.CONTROL_HEIGHT),
            False,
        )
        for item in [self._filter_all_title("Trigger"), *RUN_TRIGGER_TYPES]:
            self.trigger_popup.addItemWithTitle_(item)
        self.trigger_popup.setTarget_(self)
        self.trigger_popup.setAction_("filterSelectionChanged:")
        self.trigger_popup.setAutoresizingMask_(NSViewMinYMargin)
        self._style_filter_popup(self.trigger_popup)
        self.status_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(
                filter_layout["status_x"],
                filter_y,
                self.FILTER_STATUS_WIDTH,
                self.CONTROL_HEIGHT,
            ),
            False,
        )
        for item in [self._filter_all_title("Status"), *RUN_STATUSES]:
            self.status_popup.addItemWithTitle_(item)
        self.status_popup.setTarget_(self)
        self.status_popup.setAction_("filterSelectionChanged:")
        self.status_popup.setAutoresizingMask_(NSViewMinYMargin)
        self._style_filter_popup(self.status_popup)
        regex_x = filter_layout["query_x"]
        regex_width = filter_layout["query_width"]
        self.query_field = NSTextField.alloc().initWithFrame_(NSMakeRect(regex_x, filter_y, regex_width, self.CONTROL_HEIGHT))
        self._style_filter_text_field(self.query_field, padded=True)
        self.query_field.setStringValue_("")
        self._set_filter_placeholder(
            self.query_field,
            "Filter records - hover ? for syntax. Press Enter to apply.",
        )
        self.query_field.setTarget_(self)
        self.query_field.setAction_("queryFieldSubmitted:")
        self.query_field.setAutoresizingMask_(NSViewMinYMargin)
        help_y = filter_y + (self.CONTROL_HEIGHT - self.FILTER_HELP_WIDTH) / 2.0
        help_x = regex_x + regex_width - self.FILTER_HELP_WIDTH - 6.0
        self.query_help_icon = QueryHelpIconView.alloc().initWithFrame_(
            NSMakeRect(help_x, help_y, self.FILTER_HELP_WIDTH, self.FILTER_HELP_WIDTH)
        )
        help_image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "questionmark.circle", "Query syntax help"
        )
        if help_image is not None:
            try:
                help_image.setTemplate_(True)
            except Exception:
                pass
            self.query_help_icon.setImage_(help_image)
        if hasattr(self.query_help_icon, "setContentTintColor_"):
            self.query_help_icon.setContentTintColor_(NSColor.tertiaryLabelColor())
        self.query_help_icon.setAutoresizingMask_(NSViewMinYMargin)
        self.query_help_icon.set_hover_target(self)
        self.query_help_tooltip = FloatingTooltipController.alloc().init()
        self.query_error_tooltip = FloatingTooltipController.alloc().init()
        clear_x = filter_layout["clear_x"]
        self.clear_filters_button = self._symbol_button(
            "Reset", clear_x, filter_y, self.FILTER_CLEAR_WIDTH, "resetFiltersAction:", "xmark", "Reset filters"
        )
        filter_layout = self._filter_layout_for_content_bounds(content.bounds())
        self.refresh_button.setFrame_(
            NSMakeRect(filter_layout["refresh_x"], filter_y, filter_layout["refresh_width"], self.CONTROL_HEIGHT)
        )
        self.kind_tabs.setFrame_(NSMakeRect(filter_layout["kind_x"], filter_y, self.FILTER_KIND_WIDTH, self.CONTROL_HEIGHT))
        self.trigger_popup.setFrame_(NSMakeRect(filter_layout["trigger_x"], filter_y, self.FILTER_TRIGGER_WIDTH, self.CONTROL_HEIGHT))
        self.status_popup.setFrame_(NSMakeRect(filter_layout["status_x"], filter_y, self.FILTER_STATUS_WIDTH, self.CONTROL_HEIGHT))
        regex_x = filter_layout["query_x"]
        regex_width = filter_layout["query_width"]
        self.query_field.setFrame_(NSMakeRect(regex_x, filter_y, regex_width, self.CONTROL_HEIGHT))
        self.query_help_icon.setFrameOrigin_(
            (regex_x + regex_width - self.FILTER_HELP_WIDTH - 6.0, help_y)
        )
        self.clear_filters_button.setFrame_(
            NSMakeRect(filter_layout["clear_x"], filter_y, filter_layout["clear_width"], self.CONTROL_HEIGHT)
        )
        content.addSubview_(self.trigger_popup)
        content.addSubview_(self.status_popup)
        content.addSubview_(self.query_field)
        content.addSubview_(self.query_help_icon)
        content.addSubview_(self.clear_filters_button)

        self.list_panel = NSView.alloc().initWithFrame_(self._list_frame_for_content_bounds(content.bounds()))
        self._style_panel_view(self.list_panel, draw_border=False, clips_contents=True)
        content.addSubview_(self.list_panel)

        self.list_scroll = NSScrollView.alloc().initWithFrame_(self._panel_content_frame(self.list_panel.bounds()))
        self.list_scroll.setHasVerticalScroller_(True)
        self.list_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.list_scroll.setBorderType_(0)
        self._style_panel_view(self.list_scroll, draw_border=False, clips_contents=True)
        self.list_scroll.setDrawsBackground_(True)
        self.list_scroll.setBackgroundColor_(NSColor.whiteColor())
        self.table_view = NSTableView.alloc().initWithFrame_(self.list_scroll.bounds())
        self.table_view.setDelegate_(self)
        self.table_view.setDataSource_(self)
        self.table_view.setRowHeight_(124)
        self.table_view.setBackgroundColor_(NSColor.whiteColor())
        column = NSTableColumn.alloc().initWithIdentifier_("run")
        column.setWidth_(554)
        self.table_view.addTableColumn_(column)
        self.table_view.setHeaderView_(None)
        self.list_scroll.setDocumentView_(self.table_view)
        self.list_panel.addSubview_(self.list_scroll)
        self.list_border_overlay = self._panel_border_overlay(self.list_panel.bounds())
        self.list_panel.addSubview_(self.list_border_overlay)
        clip_view = self.list_scroll.contentView()
        if hasattr(clip_view, "setBackgroundColor_"):
            clip_view.setBackgroundColor_(NSColor.whiteColor())
        clip_view.setPostsBoundsChangedNotifications_(True)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self,
            "listClipViewBoundsDidChange:",
            NSViewBoundsDidChangeNotification,
            clip_view,
        )

        config = WKWebViewConfiguration.alloc().init()
        config.userContentController().addScriptMessageHandler_name_(self, "openExternal")
        self.detail_panel = NSView.alloc().initWithFrame_(self._detail_frame_for_content_bounds(content.bounds()))
        self._style_panel_view(self.detail_panel, draw_border=False, clips_contents=True)
        content.addSubview_(self.detail_panel)
        self.detail_web_view = AppCommandWebView.alloc().initWithFrame_configuration_(
            self._panel_content_frame(self.detail_panel.bounds()),
            config,
        )
        self.detail_web_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self._style_panel_view(self.detail_web_view, draw_border=False, clips_contents=True)
        if hasattr(self.detail_web_view, "setUnderPageBackgroundColor_"):
            self.detail_web_view.setUnderPageBackgroundColor_(NSColor.whiteColor())
        self.detail_panel.addSubview_(self.detail_web_view)
        self.detail_border_overlay = self._panel_border_overlay(self.detail_panel.bounds())
        self.detail_panel.addSubview_(self.detail_border_overlay)
        self._render_detail_payload({"message": "No selection"})

    @objc.python_method
    def _style_panel_view(self, view, draw_border: bool = True, clips_contents: bool = False) -> None:
        view.setWantsLayer_(True)
        layer = view.layer()
        if layer is None:
            return
        layer.setBackgroundColor_(NSColor.whiteColor().CGColor())
        if draw_border:
            layer.setBorderColor_(self._panel_border_color().CGColor())
            layer.setBorderWidth_(self.PANEL_BORDER_WIDTH)
        else:
            layer.setBorderWidth_(0.0)
        layer.setCornerRadius_(self.PANEL_CORNER_RADIUS)
        layer.setMasksToBounds_(clips_contents)
        if hasattr(layer, "setAllowsEdgeAntialiasing_"):
            layer.setAllowsEdgeAntialiasing_(True)

    @objc.python_method
    def _panel_border_color(self):
        return NSColor.colorWithCalibratedWhite_alpha_(0.62, 0.55)

    @objc.python_method
    def _panel_border_overlay(self, bounds):
        overlay = PanelBorderOverlay.alloc().initWithFrame_(bounds)
        overlay.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        overlay.setWantsLayer_(True)
        layer = overlay.layer()
        if layer is not None:
            layer.setBackgroundColor_(NSColor.clearColor().CGColor())
            layer.setBorderColor_(self._panel_border_color().CGColor())
            layer.setBorderWidth_(self.PANEL_BORDER_WIDTH)
            layer.setCornerRadius_(self.PANEL_CORNER_RADIUS)
            layer.setMasksToBounds_(False)
            if hasattr(layer, "setAllowsEdgeAntialiasing_"):
                layer.setAllowsEdgeAntialiasing_(True)
        return overlay

    @objc.python_method
    def _button(self, title: str, x: float, y: float, width: float, action: str):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 28))
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        button.setAutoresizingMask_(NSViewMinYMargin)
        return button

    @objc.python_method
    def _filter_font(self):
        return NSFont.systemFontOfSize_(self.CONTROL_FONT_SIZE)

    @objc.python_method
    def _apply_regular_control_style(self, control) -> None:
        font = self._filter_font()
        if hasattr(control, "setControlSize_"):
            control.setControlSize_(NSControlSizeRegular)
        if hasattr(control, "setFont_"):
            control.setFont_(font)
        cell = control.cell() if hasattr(control, "cell") else None
        if cell is not None:
            if hasattr(cell, "setControlSize_"):
                cell.setControlSize_(NSControlSizeRegular)
            if hasattr(cell, "setFont_"):
                cell.setFont_(font)

    @objc.python_method
    def _style_filter_segmented_control(self, control) -> None:
        if hasattr(control, "setFont_"):
            control.setFont_(self._filter_font())
        control.setFrameSize_((control.frame().size.width, self.CONTROL_HEIGHT))

    @objc.python_method
    def _style_filter_popup(self, popup) -> None:
        self._apply_regular_control_style(popup)
        if hasattr(popup, "setBordered_"):
            popup.setBordered_(False)
        popup.setWantsLayer_(True)
        layer = popup.layer()
        if layer is not None:
            layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.92, 1.0).CGColor())
            layer.setBorderWidth_(0.0)
            layer.setCornerRadius_(5.0)
            layer.setMasksToBounds_(False)
        popup.setFrameSize_((popup.frame().size.width, self.CONTROL_HEIGHT))

    @objc.python_method
    def _apply_filter_text_field_normal_border(self, field) -> None:
        layer = field.layer()
        if layer is None:
            return
        layer.setBackgroundColor_(NSColor.clearColor().CGColor())
        layer.setBorderColor_(NSColor.colorWithCalibratedWhite_alpha_(0.68, 0.62).CGColor())
        layer.setBorderWidth_(0.5)
        layer.setCornerRadius_(5.0)
        layer.setMasksToBounds_(False)

    @objc.python_method
    def _style_filter_text_field(self, field, padded: bool = False) -> None:
        cell = PaddedTextFieldCell.alloc().initTextCell_("") if padded else NSTextFieldCell.alloc().initTextCell_("")
        font = self._filter_font()
        cell.setEditable_(True)
        cell.setSelectable_(True)
        cell.setBezeled_(False)
        cell.setScrollable_(True)
        cell.setLineBreakMode_(2)
        cell.setUsesSingleLineMode_(True)
        cell.setControlSize_(NSControlSizeRegular)
        cell.setFont_(font)
        field.setCell_(cell)
        field.setControlSize_(NSControlSizeRegular)
        field.setFont_(font)
        field.setBezeled_(False)
        field.setBordered_(False)
        field.setDrawsBackground_(False)
        field.setBackgroundColor_(NSColor.textBackgroundColor())
        if hasattr(field, "setFocusRingType_"):
            field.setFocusRingType_(NSFocusRingTypeNone)
        field.setWantsLayer_(True)
        self._apply_filter_text_field_normal_border(field)
        field.setFrameSize_((field.frame().size.width, self.CONTROL_HEIGHT))

    @objc.python_method
    def _set_filter_placeholder(self, field, text: str) -> None:
        placeholder = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {
                NSFontAttributeName: self._filter_font(),
                NSForegroundColorAttributeName: NSColor.placeholderTextColor(),
            },
        )
        field.setPlaceholderAttributedString_(placeholder)

    @objc.python_method
    def _symbol_button(
        self,
        fallback_title: str,
        x: float,
        y: float,
        width: float,
        action: str,
        symbol: str,
        tooltip: str,
        hover_color: str = "neutral",
    ):
        return make_hover_symbol_button(
            fallback_title,
            x,
            y,
            width,
            self.CONTROL_HEIGHT,
            self,
            action,
            symbol,
            tooltip,
            hover_color=hover_button_color(hover_color),
            tooltip_controller=self.button_tooltip,
            autoresizing_mask=NSViewMinYMargin,
        )

    @objc.python_method
    def _action_symbol_button(self, attr: str, y: float):
        title, action, symbol, tooltip, hover_color, fallback_width = self.ACTION_BUTTON_SPECS[attr][:6]
        return self._symbol_button(title, 0, y, fallback_width, action, symbol, tooltip, hover_color)

    @objc.python_method
    def _layout_action_buttons(self, bounds) -> None:
        action_y = self._action_row_y_for_height_(bounds.size.height)
        button_specs = [
            (getattr(self, attr), spec[5], spec[6])
            for attr, spec in self.ACTION_BUTTON_SPECS.items()
        ]
        widths = [hover_symbol_button_width(spec[0], self.ACTION_ICON_WIDTH, spec[1]) for spec in button_specs]
        total_width = sum(widths) + sum(spec[2] for spec in button_specs[:-1])
        x = max(self.LEFT_PANEL_X, bounds.size.width - self.LEFT_PANEL_X - total_width)
        for index, spec in enumerate(button_specs):
            button = spec[0]
            gap = spec[2]
            if button is None:
                continue
            width = widths[index]
            button.setFrame_(NSMakeRect(x, action_y, width, self.CONTROL_HEIGHT))
            x += width + gap

    @objc.python_method
    def refresh_data(self) -> None:
        try:
            payload = core_client.list_runs(self._current_run_filters(offset=0))
            self.run_items = list(payload.get("items") or [])
            self.total_count = int(payload.get("total") or 0)
            self.selected_row = -1
            self.selected_message_detail = None
            self._is_loading_more = False
            self.table_view.reloadData()
            self._render_detail_payload({"message": "No selection"})
        except Exception as e:
            self._render_detail_payload({"error": f"Failed to load runs: {e}"})

    def loadMoreAction_(self, _sender) -> None:
        self._load_more_runs()

    @objc.python_method
    def _load_more_runs(self) -> None:
        if self._is_loading_more or len(self.run_items) >= self.total_count:
            return
        self._is_loading_more = True
        try:
            payload = core_client.list_runs(self._current_run_filters(offset=len(self.run_items)))
            self.total_count = int(payload.get("total") or 0)
            self.run_items.extend(payload.get("items") or [])
            self.table_view.reloadData()
        except Exception as e:
            self._show_error(str(e))
        finally:
            self._is_loading_more = False

    def resetFiltersAction_(self, _sender) -> None:
        self.kind_tabs.setSelectedSegment_(0)
        self.kind_filter = None
        self.trigger_popup.selectItemAtIndex_(0)
        self.status_popup.selectItemAtIndex_(0)
        self.query_field.setStringValue_("")
        self._clear_query_error()
        self.refresh_data()

    def filterSelectionChanged_(self, _sender) -> None:
        self.refresh_data()

    def queryFieldSubmitted_(self, _sender) -> None:
        value = str(self.query_field.stringValue() or "").strip()
        if value:
            try:
                parse_query(value)
            except ValueError as e:
                self._mark_query_error(str(e))
                return
        self._clear_query_error()
        self.refresh_data()

    def kindFilterChanged_(self, sender) -> None:
        segment = int(sender.selectedSegment())
        self.kind_filter = None if segment == 0 else MESSAGE_KINDS[segment - 1]
        self.refresh_data()

    def refreshAction_(self, _sender) -> None:
        self.refresh_data()

    def showConfigAction_(self, _sender) -> None:
        self._show_config_window(reload_from_disk=False)

    def reloadConfigAction_(self, _sender) -> None:
        self._show_config_window(reload_from_disk=True)

    def editCursorAction_(self, _sender) -> None:
        try:
            payload = core_client.get_cursor_state(self.kind_filter)
            items = list(payload.get("items") or [])
            if not items:
                self._show_error("No cursor destinations found.")
                return
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Edit Cursor")
            alert.setInformativeText_("Changes stay local in this sheet until you click Apply.")
            accessory_view, rows = self._build_cursor_accessory_view(items)
            alert.setAccessoryView_(accessory_view)
            alert.addButtonWithTitle_("Apply")
            alert.addButtonWithTitle_("Cancel")
            self._cursor_sheet_rows = rows
            alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
                self.window,
                self,
                "cursorSheetDidEnd:returnCode:contextInfo:",
                0,
            )
        except Exception as e:
            self._show_error(str(e))

    def rematchAction_(self, _sender) -> None:
        current = self._current_item()
        if current is None:
            self._show_error("Please select a run first.")
            return
        alert = self._confirmation_alert(
            "Rematch selected message?",
            (
                f"{self._selected_run_summary(current)}\n\n"
                "This will match the original message with the current runtime config and send it again."
            ),
            "Rematch",
        )
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window,
            self,
            "rematchConfirmationDidEnd:returnCode:contextInfo:",
            int(current["message_id"]),
        )

    def resendAction_(self, _sender) -> None:
        current = self._current_item()
        selected_run = self._selected_run_record()
        if current is None or selected_run is None:
            self._show_error("Please select a run first.")
            return
        options = self._collect_dest_options(selected_run)
        if not options:
            self._show_error("No destinations available in the selected run.")
            return
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 360, 28), False)
        for rule_name, dest_name in options:
            popup.addItemWithTitle_(f"{rule_name} -> {dest_name}")
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Select destination to resend")
        alert.setInformativeText_("The selected destination will be resent with the current runtime config.")
        alert.setAccessoryView_(popup)
        alert.addButtonWithTitle_("Resend")
        alert.addButtonWithTitle_("Cancel")
        self._resend_sheet_popup = popup
        self._resend_sheet_options = options
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window,
            self,
            "resendSheetDidEnd:returnCode:contextInfo:",
            int(current["message_id"]),
        )

    def deleteAction_(self, _sender) -> None:
        current = self._current_item()
        if current is None:
            self._show_error("Please select a run first.")
            return
        alert = self._confirmation_alert(
            "Delete selected run?",
            (
                f"{self._selected_run_summary(current)}\n\n"
                "This permanently removes the selected run record from local history."
            ),
            "Delete",
        )
        alert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_(
            self.window,
            self,
            "deleteConfirmationDidEnd:returnCode:contextInfo:",
            int(current["run_id"]),
        )

    @objc.python_method
    def _confirmation_alert(self, title: str, detail: str, confirm_title: str):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_(confirm_title)
        alert.addButtonWithTitle_("Cancel")
        return alert

    @objc.python_method
    def _selected_run_summary(self, item: dict[str, Any]) -> str:
        run_id = item.get("run_id")
        message_id = item.get("message_id")
        status = item.get("status") or ""
        created_at = item.get("created_at_str") or ""
        text_preview = (item.get("text_preview") or "").replace("\n", " ").strip()
        summary = f"Run ID: {run_id}\nMessage ID: {message_id}\nStatus: {status}\nCreated: {created_at}"
        if text_preview:
            summary += f"\nMessage: {text_preview}"
        return summary

    @objc.python_method
    def _perform_rematch(self, message_id: int) -> None:
        try:
            result = core_client.rematch_and_send(message_id)
            self.refresh_data()
            self._show_run_action_result("Rematch", result)
        except Exception as e:
            self._show_error(str(e))

    @objc.python_method
    def _perform_delete(self, run_id: int) -> None:
        try:
            core_client.delete_run(run_id)
            self.refresh_data()
        except Exception as e:
            self._show_error(str(e))

    def numberOfRowsInTableView_(self, _table_view) -> int:
        return len(self.run_items)

    def tableView_objectValueForTableColumn_row_(self, _table_view, _column, row: int) -> str:
        return str(row)

    def tableView_viewForTableColumn_row_(self, _table_view, _column, row: int):
        item = self.run_items[row]
        identifier = "run-cell"
        cell = self.table_view.makeViewWithIdentifier_owner_(identifier, self)
        if cell is None:
            cell = self._build_run_cell_view(identifier)
        self._populate_run_cell_view(cell, item)
        return cell

    def tableViewSelectionDidChange_(self, _notification) -> None:
        row = int(self.table_view.selectedRow())
        if row < 0 or row >= len(self.run_items):
            self.selected_row = -1
            self.selected_message_detail = None
            self._render_detail_payload({"message": "No selection"})
            return
        self.selected_row = row
        item = self.run_items[row]
        try:
            self.selected_message_detail = core_client.get_message_detail(int(item["message_id"]))
            self._render_selected_detail()
        except Exception as e:
            self._render_detail_payload({"error": f"Failed to load detail: {e}"})

    @objc.python_method
    def _render_selected_detail(self) -> None:
        current = self._current_item()
        if self.selected_message_detail is None or current is None:
            self._render_detail_payload({"message": "No selection"})
            return
        selected_run = self._selected_run_record()
        detail = {
            "message": self.selected_message_detail.get("message"),
            "selected_run_detail": selected_run,
            "all_runs": self.selected_message_detail.get("runs"),
        }
        self._render_detail_payload(detail)

    @objc.python_method
    def _selected_run_record(self) -> Optional[dict[str, Any]]:
        if self.selected_message_detail is None:
            return None
        current = self._current_item()
        if current is None:
            return None
        for run in self.selected_message_detail.get("runs") or []:
            if int(run.get("id")) == int(current["run_id"]):
                return run
        return None

    @objc.python_method
    def _collect_dest_options(self, run_record: dict[str, Any]) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        trace = run_record.get("trace") or {}
        for rule in trace.get("rules") or []:
            rule_name = rule.get("name_mark")
            for dest in rule.get("destinations") or []:
                dest_name = dest.get("name_mark")
                if rule_name and dest_name:
                    options.append((str(rule_name), str(dest_name)))
        return options

    @objc.python_method
    def _current_item(self) -> Optional[dict[str, Any]]:
        if self.selected_row < 0 or self.selected_row >= len(self.run_items):
            return None
        return self.run_items[self.selected_row]

    @objc.python_method
    def _current_run_filters(self, offset: int) -> RunQueryFilters:
        return RunQueryFilters(
            limit=self.PAGE_SIZE,
            offset=offset,
            kind=self.kind_filter,
            trigger_type=self._selected_trigger_filter(),
            status=self._selected_status_filter(),
            query=self._selected_query_filter(),
        )

    @objc.python_method
    def _filter_all_title(self, prefix: str) -> str:
        return f"{prefix}: All"

    @objc.python_method
    def _selected_trigger_filter(self) -> str | None:
        title = str(self.trigger_popup.titleOfSelectedItem() or "")
        if title == self._filter_all_title("Trigger"):
            return None
        return title

    @objc.python_method
    def _selected_status_filter(self) -> str | None:
        title = str(self.status_popup.titleOfSelectedItem() or "")
        if title == self._filter_all_title("Status"):
            return None
        return title

    @objc.python_method
    def _selected_query_filter(self) -> str | None:
        value = str(self.query_field.stringValue() or "").strip()
        return value or None

    @objc.python_method
    def _render_detail_payload(self, payload: Any) -> None:
        html = self._build_json_editor_html(payload, self.DEFAULT_COLLAPSED_DETAIL_PATHS)
        self.detail_web_view.loadHTMLString_baseURL_(html, self._jsoneditor_base_url)

    @objc.python_method
    def _show_config_window(self, reload_from_disk: bool) -> None:
        self._ensure_config_window()
        self._move_config_window_to_current_screen()
        self.config_window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        try:
            if reload_from_disk:
                if self.app_controller is None:
                    raise RuntimeError("App controller is not available.")
                self.app_controller.restart_managed_core()
            payload = core_client.get_built_config()
            built_cfg = payload.get("built_cfg") or {}
            self.config_window.setTitle_(f"Built Config - {payload.get('config_file_path') or ''}")
            self._render_config_payload(built_cfg)
            if reload_from_disk:
                self.refresh_data()
        except Exception as e:
            self._render_config_payload({"error": f"Failed to load built config: {e}"})
            self._show_error(str(e))

    @objc.python_method
    def _ensure_config_window(self) -> None:
        if self.config_window is not None:
            return
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        self.config_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, self.CONFIG_WINDOW_WIDTH, self.CONFIG_WINDOW_HEIGHT),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.config_window.setTitle_("Built Config")
        self.config_window.setReleasedWhenClosed_(False)
        content = self.config_window.contentView()
        padding = self.CONFIG_WINDOW_PADDING
        button_y = self.CONFIG_WINDOW_HEIGHT - padding - self.CONTROL_HEIGHT
        self.config_reload_button = self._button("Reload", padding, button_y, 92.0, "reloadConfigAction:")
        self.config_reload_button.setAutoresizingMask_(NSViewMinYMargin)
        content.addSubview_(self.config_reload_button)
        config = WKWebViewConfiguration.alloc().init()
        config.userContentController().addScriptMessageHandler_name_(self, "openExternal")
        web_y = padding
        web_height = button_y - padding - 10.0
        self.config_web_view = AppCommandWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(
                padding,
                web_y,
                self.CONFIG_WINDOW_WIDTH - padding * 2,
                web_height,
            ),
            config,
        )
        self.config_web_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content.addSubview_(self.config_web_view)

    @objc.python_method
    def _render_config_payload(self, payload: Any) -> None:
        if self.config_web_view is None:
            return
        html = self._build_json_editor_html(payload, (), expand_all=True)
        self.config_web_view.loadHTMLString_baseURL_(html, self._jsoneditor_base_url)

    @objc.python_method
    def _build_cursor_accessory_view(self, items: list[dict[str, Any]]):
        width = 640.0
        row_height = 32.0
        header_height = 22.0
        kind_width = 60.0
        dest_width = 390.0
        field_width = 160.0
        kind_x = 0.0
        dest_x = kind_x + kind_width + 10.0
        field_x = dest_x + dest_width + 10.0
        body_height = max(row_height, len(items) * row_height)
        total_height = header_height + body_height
        visible_height = min(max(total_height, 96.0), 320.0)
        document_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, total_height))
        header_y = total_height - header_height
        for header_text, header_x, header_w in (
            ("Kind", kind_x, kind_width),
            ("Destination", dest_x, dest_width),
            ("Cursor", field_x, field_width),
        ):
            header_label = self._label(
                NSMakeRect(header_x, header_y + 2, header_w, 18),
                size=11,
                bold=True,
                color=NSColor.secondaryLabelColor(),
            )
            header_label.setStringValue_(header_text)
            document_view.addSubview_(header_label)
        rows: list[tuple[str, str, Any]] = []
        for idx, item in enumerate(items):
            kind = str(item.get("kind") or "")
            dest_name = str(item.get("destination") or "")
            row_y = header_y - ((idx + 1) * row_height)
            kind_label = self._label(
                NSMakeRect(kind_x, row_y + 6, kind_width, 18),
                size=12,
                color=NSColor.secondaryLabelColor(),
            )
            kind_label.setStringValue_(kind)
            dest_label = self._readable_single_line_text(
                NSMakeRect(dest_x, row_y + 6, dest_width, 18),
                size=12,
                color=NSColor.labelColor(),
            )
            dest_label.setStringValue_(dest_name)
            dest_label.setToolTip_(dest_name)
            field = NSTextField.alloc().initWithFrame_(NSMakeRect(field_x, row_y + 2, field_width, self.CONTROL_HEIGHT))
            field.setStringValue_(self._format_cursor_value(item.get("cursor_value")))
            document_view.addSubview_(kind_label)
            document_view.addSubview_(dest_label)
            document_view.addSubview_(field)
            rows.append((kind, dest_name, field))
        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, width, visible_height))
        scroll_view.setHasVerticalScroller_(total_height > visible_height)
        scroll_view.setDocumentView_(document_view)
        document_view.scrollPoint_(NSMakePoint(0.0, total_height))
        return scroll_view, rows

    @objc.python_method
    def _format_cursor_value(self, value: Any) -> str:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ""
        return format(float(value), ".15g")

    @objc.python_method
    def _build_detail_html(self, payload: Any) -> str:
        return self._build_json_editor_html(payload, self.DEFAULT_COLLAPSED_DETAIL_PATHS)

    @objc.python_method
    def _build_json_editor_html(self, payload: Any, collapsed_paths: tuple = (), expand_all: bool = False) -> str:
        data_json = self._json_for_inline_script(payload)
        collapsed_paths_json = self._json_for_inline_script(collapsed_paths)
        expand_all_json = self._json_for_inline_script(expand_all)
        jsoneditor_js = self._jsoneditor_js_source
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body, #jsoneditor {{
      margin: 0;
      width: 100%;
      height: 100%;
    }}
    body {{
      background: #ffffff;
      overflow: hidden;
    }}
    #jsoneditor {{
      --jse-theme-color: #2b2b2b;
      --jse-main-border: none;
      border: 0 !important;
      box-shadow: none !important;
    }}
    #jsoneditor .jse-main {{
      border: 0 !important;
      box-shadow: none !important;
    }}
  </style>
</head>
<body>
  <div id="jsoneditor"></div>
  <script>{jsoneditor_js}</script>
  <script>
    let content = {{
      json: {data_json},
      text: undefined
    }};
    const collapsedPaths = {collapsed_paths_json};
    const expandAll = {expand_all_json};
    const container = document.getElementById('jsoneditor');

    function handleChange(updatedContent) {{
      content = updatedContent;
    }}

    const createJSONEditor = window.createJSONEditor;
    const editor = createJSONEditor({{
      target: container,
      props: {{
        content,
        mode: 'tree',
        readOnly: true,
        mainMenuBar: true,
        navigationBar: true,
        statusBar: true,
        onChange: handleChange
      }}
    }});
    window.msgflowEditor = editor;

    try {{
      if (expandAll && typeof editor.expand === 'function') {{
        editor.expand([], () => true);
      }} else if (typeof editor.collapse === 'function') {{
        collapsedPaths.forEach((path) => {{
          editor.collapse(path, true);
        }});
      }}
    }} catch (error) {{
      console.warn('Failed to apply JSON editor expansion state', error);
    }}
  </script>
</body>
</html>"""

    @objc.python_method
    def _json_for_inline_script(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str).replace("</", "<\\/")

    @objc.python_method
    def _load_svelte_jsoneditor_js_for_inline_script(self) -> str:
        source = (assets_dir() / "svelte-jsoneditor.js").read_text(encoding="utf-8")
        export_match = re.search(r"export\{(?P<exports>.*?)\};", source, re.DOTALL)
        if export_match is None:
            raise RuntimeError("svelte-jsoneditor.js does not contain an ESM export block.")
        create_match = re.search(r"([A-Za-z_$][\w$]*)\s+as\s+createJSONEditor", export_match.group("exports"))
        if create_match is None:
            raise RuntimeError("svelte-jsoneditor.js does not export createJSONEditor.")
        create_symbol = create_match.group(1)
        source = (
            source[: export_match.start()]
            + f"window.createJSONEditor = {create_symbol};"
            + source[export_match.end() :]
        )
        source = re.sub(r"\n//# sourceMappingURL=.*$", "", source)
        return source.replace("</script", "<\\/script")

    @objc.python_method
    def _list_frame_for_content_bounds(self, bounds):
        content_height = bounds.size.height
        filter_y = self._filter_row_y_for_height_(content_height)
        list_top = filter_y - self.FILTER_TO_LIST_GAP
        list_height = max(200.0, list_top - self.CONTENT_BOTTOM)
        return NSMakeRect(
            self.LEFT_PANEL_X,
            self.CONTENT_BOTTOM,
            self.LEFT_PANEL_WIDTH,
            list_height,
        )

    @objc.python_method
    def _detail_frame_for_content_bounds(self, bounds):
        content_height = bounds.size.height
        detail_x = self.LEFT_PANEL_X + self.LEFT_PANEL_WIDTH + self.DETAIL_GAP
        detail_width = max(360.0, bounds.size.width - detail_x - 20.0)
        filter_y = self._filter_row_y_for_height_(content_height)
        list_top = filter_y - self.FILTER_TO_LIST_GAP
        detail_height = max(200.0, list_top - self.CONTENT_BOTTOM)
        return NSMakeRect(
            detail_x,
            self.CONTENT_BOTTOM,
            detail_width,
            detail_height,
        )

    @objc.python_method
    def _panel_content_frame(self, bounds):
        inset = self.PANEL_CONTENT_INSET
        return NSMakeRect(
            inset,
            inset,
            max(1.0, bounds.size.width - inset * 2.0),
            max(1.0, bounds.size.height - inset * 2.0),
        )

    @objc.python_method
    def _action_row_y_for_height_(self, content_height: float) -> float:
        return content_height - self.TOP_MARGIN - self.CONTROL_HEIGHT

    @objc.python_method
    def _filter_row_y_for_height_(self, content_height: float) -> float:
        return self._action_row_y_for_height_(content_height) - self.ACTION_TO_FILTER_GAP - self.CONTROL_HEIGHT

    @objc.python_method
    def _filter_layout_for_content_bounds(self, bounds) -> dict[str, float]:
        row_width = max(self.LEFT_PANEL_WIDTH, bounds.size.width - self.LEFT_PANEL_X * 2)
        refresh_width = hover_symbol_button_width(self.refresh_button, self.FILTER_REFRESH_WIDTH, 70.0)
        clear_width = hover_symbol_button_width(self.clear_filters_button, self.FILTER_CLEAR_WIDTH, 64.0)
        refresh_x = self.LEFT_PANEL_X
        kind_x = refresh_x + refresh_width + self.FILTER_GAP
        trigger_x = kind_x + self.FILTER_KIND_WIDTH + self.FILTER_GAP
        status_x = trigger_x + self.FILTER_TRIGGER_WIDTH + self.FILTER_GAP
        query_x = status_x + self.FILTER_STATUS_WIDTH + self.FILTER_GAP
        clear_x = self.LEFT_PANEL_X + row_width - clear_width
        query_width = max(160.0, clear_x - query_x - self.FILTER_GAP)
        return {
            "refresh_x": refresh_x,
            "refresh_width": refresh_width,
            "kind_x": kind_x,
            "trigger_x": trigger_x,
            "status_x": status_x,
            "query_x": query_x,
            "query_width": query_width,
            "clear_x": clear_x,
            "clear_width": clear_width,
        }

    @objc.python_method
    def _relayout_content(self) -> None:
        if (
            self.window is None
            or self.list_panel is None
            or self.list_scroll is None
            or self.detail_panel is None
            or self.detail_web_view is None
        ):
            return
        bounds = self.window.contentView().bounds()
        filter_y = self._filter_row_y_for_height_(bounds.size.height)
        filter_layout = self._filter_layout_for_content_bounds(bounds)
        self.refresh_button.setFrame_(
            NSMakeRect(filter_layout["refresh_x"], filter_y, filter_layout["refresh_width"], self.CONTROL_HEIGHT)
        )
        self.kind_tabs.setFrame_(NSMakeRect(filter_layout["kind_x"], filter_y, self.FILTER_KIND_WIDTH, self.CONTROL_HEIGHT))
        self._layout_action_buttons(bounds)
        self.trigger_popup.setFrame_(NSMakeRect(filter_layout["trigger_x"], filter_y, self.FILTER_TRIGGER_WIDTH, self.CONTROL_HEIGHT))
        self.status_popup.setFrame_(NSMakeRect(filter_layout["status_x"], filter_y, self.FILTER_STATUS_WIDTH, self.CONTROL_HEIGHT))
        regex_x = filter_layout["query_x"]
        regex_width = filter_layout["query_width"]
        self.query_field.setFrame_(NSMakeRect(regex_x, filter_y, regex_width, self.CONTROL_HEIGHT))
        if self.query_help_icon is not None:
            help_x = regex_x + regex_width - self.FILTER_HELP_WIDTH - 6.0
            help_y = filter_y + (self.CONTROL_HEIGHT - self.FILTER_HELP_WIDTH) / 2.0
            self.query_help_icon.setFrameOrigin_((help_x, help_y))
        self.clear_filters_button.setFrame_(
            NSMakeRect(filter_layout["clear_x"], filter_y, filter_layout["clear_width"], self.CONTROL_HEIGHT)
        )
        self.list_panel.setFrame_(self._list_frame_for_content_bounds(bounds))
        self.list_scroll.setFrame_(self._panel_content_frame(self.list_panel.bounds()))
        self.detail_panel.setFrame_(self._detail_frame_for_content_bounds(bounds))
        self.detail_web_view.setFrame_(self._panel_content_frame(self.detail_panel.bounds()))
        self.detail_web_view.evaluateJavaScript_completionHandler_(
            "if (window.msgflowEditor && window.msgflowEditor.refresh) { window.msgflowEditor.refresh(); }",
            None,
        )

    def windowDidResize_(self, _notification) -> None:
        self._relayout_content()

    def windowShouldClose_(self, sender) -> bool:
        sender.orderOut_(None)
        return False

    def listClipViewBoundsDidChange_(self, _notification) -> None:
        if self.list_scroll is None or self.table_view is None:
            return
        visible_rect = self.list_scroll.documentVisibleRect()
        table_height = self.table_view.bounds().size.height
        if visible_rect.origin.y + visible_rect.size.height >= table_height - self.AUTO_LOAD_THRESHOLD:
            self._load_more_runs()

    def userContentController_didReceiveScriptMessage_(self, _controller, message) -> None:
        if str(message.name()) != "openExternal":
            return
        url = NSURL.URLWithString_(str(message.body()))
        if url is not None:
            NSWorkspace.sharedWorkspace().openURL_(url)

    @objc.selectorFor(NSAlert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_)
    def rematchConfirmationDidEnd_returnCode_contextInfo_(self, _alert, returnCode, contextInfo) -> None:
        if int(returnCode) != 1000:
            return
        self._perform_rematch(int(contextInfo))

    @objc.selectorFor(NSAlert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_)
    def resendSheetDidEnd_returnCode_contextInfo_(self, _alert, returnCode, contextInfo) -> None:
        if int(returnCode) != 1000 or self._resend_sheet_popup is None:
            self._resend_sheet_popup = None
            self._resend_sheet_options = []
            return
        selected_title = self._resend_sheet_popup.titleOfSelectedItem()
        selected_rule, selected_dest = next(
            (item for item in self._resend_sheet_options if f"{item[0]} -> {item[1]}" == selected_title),
            self._resend_sheet_options[0],
        )
        self._resend_sheet_popup = None
        self._resend_sheet_options = []
        try:
            result = core_client.resend_destination(int(contextInfo), selected_rule, selected_dest)
            self.refresh_data()
            self._show_run_action_result("Resend", result)
        except Exception as e:
            self._show_error(str(e))

    @objc.selectorFor(NSAlert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_)
    def deleteConfirmationDidEnd_returnCode_contextInfo_(self, _alert, returnCode, contextInfo) -> None:
        if int(returnCode) != 1000:
            return
        self._perform_delete(int(contextInfo))

    @objc.selectorFor(NSAlert.beginSheetModalForWindow_modalDelegate_didEndSelector_contextInfo_)
    def cursorSheetDidEnd_returnCode_contextInfo_(self, _alert, returnCode, _contextInfo) -> None:
        if int(returnCode) != 1000 or not self._cursor_sheet_rows:
            self._cursor_sheet_rows = []
            return
        try:
            per_kind: dict[str, dict[str, float]] = {}
            for kind, dest_name, field in self._cursor_sheet_rows:
                raw_value = str(field.stringValue() or "").strip()
                if not raw_value:
                    raise ValueError(f"cursor for '{dest_name}' ({kind}) cannot be empty")
                per_kind.setdefault(kind, {})[dest_name] = float(raw_value)
            for kind, cursor_map in per_kind.items():
                if cursor_map:
                    core_client.update_cursor_state(kind, cursor_map)
            self.refresh_data()
        except Exception as e:
            self._show_error(str(e))
        finally:
            self._cursor_sheet_rows = []

    @objc.python_method
    def _build_run_cell_view(self, identifier: str):
        width = 548.0
        cell = NSTableCellView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 124))
        cell.setIdentifier_(identifier)

        line1_left = self._label(NSMakeRect(12, 96, 128, 18), bold=True)
        line1_middle = self._label(NSMakeRect(146, 96, 208, 18), bold=True, align=1)
        line1_right = self._label(NSMakeRect(360, 96, 160, 18), size=11, align=2)
        line2 = self._label(NSMakeRect(12, 72, 508, 18), color=NSColor.secondaryLabelColor())
        line3 = self._label(NSMakeRect(12, 34, 508, 34), color=NSColor.labelColor(), wrap=True)
        line4_left = self._label(NSMakeRect(12, 12, 110, 16), size=11, color=NSColor.secondaryLabelColor())
        line4_middle = self._label(NSMakeRect(150, 12, 220, 16), size=11, color=NSColor.secondaryLabelColor(), align=1)
        line4_right = self._label(NSMakeRect(392, 12, 128, 16), size=11, color=NSColor.secondaryLabelColor(), align=2)
        separator = NSBox.alloc().initWithFrame_(NSMakeRect(10, 1, 512, 1))
        separator.setBoxType_(2)
        separator.setBorderColor_(NSColor.separatorColor())

        line1_left.setTag_(self.TAG_LINE1_LEFT)
        line1_middle.setTag_(self.TAG_LINE1_MIDDLE)
        line1_right.setTag_(self.TAG_LINE1_RIGHT)
        line2.setTag_(self.TAG_LINE2)
        line3.setTag_(self.TAG_LINE3)
        line4_left.setTag_(self.TAG_LINE4_LEFT)
        line4_middle.setTag_(self.TAG_LINE4_MIDDLE)
        line4_right.setTag_(self.TAG_LINE4_RIGHT)
        cell.addSubview_(line1_left)
        cell.addSubview_(line1_middle)
        cell.addSubview_(line1_right)
        cell.addSubview_(line2)
        cell.addSubview_(line3)
        cell.addSubview_(line4_left)
        cell.addSubview_(line4_middle)
        cell.addSubview_(line4_right)
        cell.addSubview_(separator)
        return cell

    @objc.python_method
    def _populate_run_cell_view(self, cell, item: dict[str, Any]) -> None:
        sender = item.get("sender") or ""
        receiver = item.get("receiver") or ""
        text_preview = (item.get("text_preview") or "").replace("\n", " ").strip()
        cursor_value = item.get("cursor_value")
        cursor_text = "" if cursor_value is None else str(cursor_value)
        line1_left = cell.viewWithTag_(self.TAG_LINE1_LEFT)
        line1_middle = cell.viewWithTag_(self.TAG_LINE1_MIDDLE)
        line1_right = cell.viewWithTag_(self.TAG_LINE1_RIGHT)
        line2 = cell.viewWithTag_(self.TAG_LINE2)
        line3 = cell.viewWithTag_(self.TAG_LINE3)
        line4_left = cell.viewWithTag_(self.TAG_LINE4_LEFT)
        line4_middle = cell.viewWithTag_(self.TAG_LINE4_MIDDLE)
        line4_right = cell.viewWithTag_(self.TAG_LINE4_RIGHT)
        line1_left.setStringValue_(f"{item.get('run_id')}({item.get('message_id')})")
        line1_middle.setStringValue_(str(item.get("status") or ""))
        line1_right.setStringValue_(str(item.get("created_at_str") or ""))
        line2.setStringValue_(f"{sender} -> {receiver}")
        line3.setStringValue_(text_preview)
        line4_left.setStringValue_(str(item.get("trigger_type") or ""))
        line4_middle.setStringValue_(str(item.get("time_str") or ""))
        line4_right.setStringValue_(cursor_text)

    @objc.python_method
    def _label(self, frame, size: float = 12, bold: bool = False, color=None, align: int = 0, wrap: bool = False):
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(align)
        label.setLineBreakMode_(0 if wrap else 4)
        label.setUsesSingleLineMode_(not wrap)
        label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if wrap:
            label.cell().setWraps_(True)
        if color is not None:
            label.setTextColor_(color)
        return label

    @objc.python_method
    def _readable_single_line_text(self, frame, size: float = 12, color=None):
        field = NSTextField.alloc().initWithFrame_(frame)
        field.setBezeled_(False)
        field.setBordered_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(True)
        field.setLineBreakMode_(2)
        field.setUsesSingleLineMode_(True)
        field.cell().setScrollable_(True)
        field.setFont_(NSFont.systemFontOfSize_(size))
        if color is not None:
            field.setTextColor_(color)
        if hasattr(field, "setFocusRingType_"):
            field.setFocusRingType_(NSFocusRingTypeNone)
        return field

    @objc.python_method
    def _show_error(self, text: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Error")
        alert.setInformativeText_(text)
        alert.runModal()

    @objc.python_method
    def _show_query_help_tooltip(self) -> None:
        if self.query_help_tooltip is None or self.query_help_icon is None:
            return
        self.query_help_tooltip.show_from_view(self.query_help_icon, QUERY_HELP_TEXT, max_width=420.0)

    @objc.python_method
    def _hide_query_help_tooltip(self) -> None:
        if self.query_help_tooltip is not None:
            self.query_help_tooltip.hide()

    @objc.python_method
    def _mark_query_error(self, message: str) -> None:
        if self.query_field is None:
            return
        self.query_field.setWantsLayer_(True)
        layer = self.query_field.layer()
        if layer is not None:
            layer.setBorderColor_(NSColor.systemRedColor().colorWithAlphaComponent_(0.55).CGColor())
            layer.setBorderWidth_(1.0)
            layer.setCornerRadius_(4.0)
        self._query_field_error = True
        if self.query_error_tooltip is not None:
            self.query_error_tooltip.show_from_view(self.query_field, message, max_width=420.0)

    @objc.python_method
    def _clear_query_error(self) -> None:
        if self._query_field_error and self.query_field is not None:
            self._apply_filter_text_field_normal_border(self.query_field)
        self._query_field_error = False
        if self.query_error_tooltip is not None:
            self.query_error_tooltip.hide()

    @objc.python_method
    def _show_run_action_result(self, action_name: str, payload: dict[str, Any]) -> None:
        status = str(payload.get("status") or "").strip().lower()
        run_id = payload.get("run_id")
        title = f"{action_name}"
        detail = f"{action_name} Status: {status}\nRun ID: {run_id}"
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.runModal()
