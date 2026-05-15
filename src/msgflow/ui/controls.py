from math import ceil

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSImage,
    NSImageView,
    NSLineBreakByWordWrapping,
    NSMakeRect,
    NSPanel,
    NSStringDrawingUsesLineFragmentOrigin,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSAttributedString, NSObject


class HoverIconButton(NSButton):
    def initWithFrame_(self, frame):  # type: ignore[override]
        self = objc.super(HoverIconButton, self).initWithFrame_(frame)
        if self is None:
            return None
        self._tracking_area = None
        self._icon_view = None
        self._symbol_name = "xmark"
        self._fallback_title = ""
        self._symbol_size = 13.0
        self._icon_inset_x = 0.0
        self._icon_inset_y = 0.0
        self._hover_text = ""
        self._base_foreground = NSColor.colorWithCalibratedWhite_alpha_(0.42, 0.92)
        self._hover_foreground = NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0)
        self._base_background = NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.66)
        self._hover_background = NSColor.colorWithCalibratedWhite_alpha_(0.56, 0.14)
        self._base_border = NSColor.colorWithCalibratedWhite_alpha_(0.80, 0.34)
        self._hover_border = NSColor.colorWithCalibratedWhite_alpha_(0.74, 0.12)
        self._has_symbol = False
        self._tooltip_controller = None
        self.setBordered_(False)
        self.setWantsLayer_(True)
        self.setTitle_("")
        self.setFont_(NSFont.systemFontOfSize_(11.0))
        self.setImage_(None)
        self._icon_view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
        if self._icon_view is not None:
            self.addSubview_(self._icon_view)
        self._apply_appearance(False)
        return self

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
        objc.super(HoverIconButton, self).updateTrackingAreas()

    def mouseEntered_(self, _event) -> None:
        self._apply_appearance(True)
        if self._tooltip_controller is not None:
            self._tooltip_controller.show_from_button(self, self.hover_text())
            return
        target = self.target()
        if target is not None and hasattr(target, "_show_button_tooltip_for"):
            target._show_button_tooltip_for(self)

    def mouseExited_(self, _event) -> None:
        self._apply_appearance(False)
        if self._tooltip_controller is not None:
            self._tooltip_controller.hide()
            return
        target = self.target()
        if target is not None and hasattr(target, "_hide_button_tooltip_for"):
            target._hide_button_tooltip_for(self)

    @objc.python_method
    def configure(
        self,
        symbol_name: str,
        tooltip: str,
        symbol_size: float,
        icon_inset_x: float,
        icon_inset_y: float,
        base_foreground=None,
        hover_foreground=None,
        base_background=None,
        hover_background=None,
        base_border=None,
        hover_border=None,
        fallback_title: str = "",
    ) -> None:
        self._symbol_name = symbol_name
        self._fallback_title = fallback_title
        self._symbol_size = symbol_size
        self._icon_inset_x = icon_inset_x
        self._icon_inset_y = icon_inset_y
        self._hover_text = tooltip
        self._base_foreground = base_foreground or NSColor.colorWithCalibratedWhite_alpha_(0.42, 0.92)
        self._hover_foreground = hover_foreground or NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0)
        self._base_background = base_background or NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.66)
        self._hover_background = hover_background or NSColor.colorWithCalibratedWhite_alpha_(0.56, 0.14)
        self._base_border = base_border if base_border is not None else NSColor.colorWithCalibratedWhite_alpha_(0.80, 0.34)
        self._hover_border = hover_border if hover_border is not None else NSColor.colorWithCalibratedWhite_alpha_(0.74, 0.12)
        self._apply_appearance(False)

    @objc.python_method
    def set_hover_text(self, text: str) -> None:
        self._hover_text = text

    @objc.python_method
    def hover_text(self) -> str:
        return str(self._hover_text or "")

    @objc.python_method
    def uses_symbol(self) -> bool:
        return bool(self._has_symbol)

    @objc.python_method
    def set_tooltip_controller(self, tooltip_controller) -> None:
        self._tooltip_controller = tooltip_controller

    @objc.python_method
    def preferred_width(self, icon_width: float, fallback_width: float) -> float:
        if self.uses_symbol() and not str(self.title() or ""):
            return icon_width
        return fallback_width

    def setFrame_(self, frame) -> None:  # type: ignore[override]
        objc.super(HoverIconButton, self).setFrame_(frame)
        self._layout_icon()

    @objc.python_method
    def _layout_icon(self) -> None:
        if self._icon_view is None:
            return
        bounds = self.bounds()
        icon_width = max(1.0, bounds.size.width - self._icon_inset_x * 2.0)
        icon_height = max(1.0, bounds.size.height - self._icon_inset_y * 2.0)
        self._icon_view.setFrame_(
            NSMakeRect(
                self._icon_inset_x,
                self._icon_inset_y,
                icon_width,
                icon_height,
            )
        )

    @objc.python_method
    def _symbol_image(self):
        if not hasattr(NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
            return None
        symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            self._symbol_name,
            self._hover_text,
        )
        if symbol is None:
            return None
        symbol.setTemplate_(True)
        symbol.setSize_((self._symbol_size, self._symbol_size))
        return symbol

    @objc.python_method
    def _apply_appearance(self, hovered: bool) -> None:
        foreground = self._hover_foreground if hovered else self._base_foreground
        background = self._hover_background if hovered else self._base_background
        border = self._hover_border if hovered else self._base_border
        symbol = self._symbol_image()
        self._has_symbol = symbol is not None
        if symbol is None:
            if self._icon_view is not None:
                self._icon_view.setHidden_(True)
            self.setTitle_(self._fallback_title)
            if hasattr(self, "setContentTintColor_"):
                self.setContentTintColor_(foreground)
        else:
            self.setTitle_("")
            if self._icon_view is not None:
                self._icon_view.setHidden_(False)
                self._icon_view.setImage_(symbol)
                if hasattr(self._icon_view, "setImageScaling_"):
                    self._icon_view.setImageScaling_(3)
                if hasattr(self._icon_view, "setContentTintColor_"):
                    self._icon_view.setContentTintColor_(foreground)
        self._layout_icon()
        layer = self.layer()
        if layer is not None:
            layer.setCornerRadius_(9.5)
            layer.setBackgroundColor_(background.CGColor())
            layer.setBorderWidth_(0.45 if border != NSColor.clearColor() else 0.0)
            layer.setBorderColor_(border.CGColor())
            layer.setShadowColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.085).CGColor())
            layer.setShadowOpacity_(1.0)
            layer.setShadowRadius_(1.2 if hovered else 1.6)
            layer.setShadowOffset_((0.0, -0.55))


def _color_with_alpha(color, alpha: float):
    if hasattr(color, "colorWithAlphaComponent_"):
        return color.colorWithAlphaComponent_(alpha)
    return color


def hover_button_color(name: str):
    if name == "blue":
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.07, 0.41, 0.93, 1.0)
    if name == "green":
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.13, 0.60, 0.29, 1.0)
    if name == "red":
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.74, 0.24, 0.24, 1.0)
    if name == "purple":
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.42, 0.30, 0.86, 1.0)
    return NSColor.colorWithCalibratedWhite_alpha_(0.18, 1.0)


def configure_hover_symbol_button(
    button,
    symbol_name: str,
    tooltip: str,
    fallback_title: str,
    hover_color=None,
    *,
    symbol_size: float = 15.0,
    icon_inset_x: float = 7.0,
    icon_inset_y: float = 5.5,
) -> None:
    hover_color = hover_color or hover_button_color("neutral")
    button.configure(
        symbol_name,
        tooltip,
        symbol_size,
        icon_inset_x,
        icon_inset_y,
        NSColor.colorWithCalibratedWhite_alpha_(0.42, 0.98),
        hover_color,
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.60),
        _color_with_alpha(hover_color, 0.11),
        NSColor.colorWithCalibratedWhite_alpha_(0.76, 0.88),
        _color_with_alpha(hover_color, 0.16),
        fallback_title=fallback_title,
    )


def make_hover_symbol_button(
    fallback_title: str,
    x: float,
    y: float,
    width: float,
    height: float,
    target,
    action: str,
    symbol_name: str,
    tooltip: str,
    *,
    hover_color=None,
    tooltip_controller=None,
    autoresizing_mask=None,
    symbol_size: float = 15.0,
    icon_inset_x: float = 7.0,
    icon_inset_y: float = 5.5,
):
    button = HoverIconButton.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
    configure_hover_symbol_button(
        button,
        symbol_name,
        tooltip,
        fallback_title,
        hover_color,
        symbol_size=symbol_size,
        icon_inset_x=icon_inset_x,
        icon_inset_y=icon_inset_y,
    )
    button.setTarget_(target)
    button.setAction_(action)
    if tooltip_controller is not None:
        button.set_tooltip_controller(tooltip_controller)
    if autoresizing_mask is not None:
        button.setAutoresizingMask_(autoresizing_mask)
    return button


def hover_symbol_button_width(button, icon_width: float, fallback_width: float) -> float:
    if button is None:
        return icon_width
    return button.preferred_width(icon_width, fallback_width)


class FloatingTooltipController(NSObject):
    def init(self):  # type: ignore[override]
        self = objc.super(FloatingTooltipController, self).init()
        if self is None:
            return None
        self.panel = None
        self.label = None
        self._font = NSFont.systemFontOfSize_(10.5)
        self._horizontal_padding = 5.0
        self._vertical_padding = 4.0
        return self

    @objc.python_method
    def show_from_button(self, button, text: str) -> None:
        if not text:
            self.hide()
            return
        window = button.window()
        if window is None:
            return
        button_frame_in_window = button.convertRect_toView_(button.bounds(), None)
        button_screen_frame = window.convertRectToScreen_(button_frame_in_window)
        screen = button.window().screen()
        visible_frame = screen.visibleFrame() if screen is not None else None
        text_width = self._measure_text_width(text)
        max_panel_width = (
            max(120.0, visible_frame.size.width - 12.0)
            if visible_frame is not None
            else 720.0
        )
        panel_width = min(max(56.0, text_width + self._horizontal_padding * 2.0), max_panel_width)
        panel_height = 24.0
        preferred_x = button_screen_frame.origin.x + button_screen_frame.size.width * 0.60
        preferred_y = button_screen_frame.origin.y + button_screen_frame.size.height + 8.0
        if visible_frame is not None:
            min_x = visible_frame.origin.x + 6.0
            max_x = visible_frame.origin.x + visible_frame.size.width - panel_width - 6.0
            preferred_x = min(max(preferred_x, min_x), max_x if max_x >= min_x else min_x)
            max_y = visible_frame.origin.y + visible_frame.size.height - panel_height - 6.0
            if preferred_y > max_y:
                preferred_y = button_screen_frame.origin.y - panel_height - 8.0
        self._show(text, NSMakeRect(preferred_x, preferred_y, panel_width, panel_height), panel_width, panel_height)
        self.label.setUsesSingleLineMode_(True)
        self.label.setLineBreakMode_(2)
        self.label.setAlignment_(1)
        self.label.setFrame_(self._label_frame(panel_width))

    @objc.python_method
    def hide(self) -> None:
        if self.panel is not None:
            self.panel.orderOut_(None)

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
        self.panel.setIgnoresMouseEvents_(True)
        content_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, frame.size.height))
        content_view.setWantsLayer_(True)
        content_layer = content_view.layer()
        if content_layer is not None:
            content_layer.setCornerRadius_(7.0)
            content_layer.setMasksToBounds_(False)
            content_layer.setBackgroundColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.87, 0.985).CGColor()
            )
            content_layer.setBorderWidth_(0.55)
            content_layer.setBorderColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.69, 0.42).CGColor()
            )
            content_layer.setShadowColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.18).CGColor()
            )
            content_layer.setShadowOpacity_(1.0)
            content_layer.setShadowRadius_(8.5)
            content_layer.setShadowOffset_((0.0, -1.5))
        self.panel.setContentView_(content_view)
        self.label = NSTextField.alloc().initWithFrame_(
            self._label_frame(frame.size.width)
        )
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(False)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setFont_(self._font)
        self.label.setAlignment_(1)
        self.label.setUsesSingleLineMode_(True)
        self.label.setLineBreakMode_(2)
        self.label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.16, 0.98))
        content_view.addSubview_(self.label)

    @objc.python_method
    def _show(self, text: str, frame, panel_width: float, panel_height: float) -> None:
        if self.panel is None:
            self._create_panel(frame)
        else:
            self.panel.setFrame_display_(frame, True)
            content_view = self.panel.contentView()
            if content_view is not None:
                content_view.setFrame_(NSMakeRect(0.0, 0.0, panel_width, panel_height))
        self.label.setStringValue_(text)
        self.panel.orderFrontRegardless()

    @objc.python_method
    def _label_frame(self, panel_width: float):
        return NSMakeRect(
            self._horizontal_padding,
            4.0,
            panel_width - self._horizontal_padding * 2.0,
            14.0,
        )

    @objc.python_method
    def _measure_text_width(self, text: str) -> float:
        attributed = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: self._font},
        )
        return float(attributed.size().width + 10.0)

    @objc.python_method
    def show_from_view(self, view, text: str, *, max_width: float = 360.0) -> None:
        if not text or view is None:
            self.hide()
            return
        window = view.window()
        if window is None:
            return
        view_frame_in_window = view.convertRect_toView_(view.bounds(), None)
        view_screen_frame = window.convertRectToScreen_(view_frame_in_window)
        attributed = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: self._font},
        )
        bounding = attributed.boundingRectWithSize_options_(
            (max_width - self._horizontal_padding * 2.0, 10000.0),
            NSStringDrawingUsesLineFragmentOrigin,
        )
        text_width = float(ceil(bounding.size.width))
        text_height = float(ceil(bounding.size.height))
        panel_width = min(
            max(120.0, text_width + self._horizontal_padding * 2.0),
            max_width,
        )
        panel_height = max(24.0, text_height + self._vertical_padding * 2.0 + 4.0)
        screen = window.screen()
        visible_frame = screen.visibleFrame() if screen is not None else None
        preferred_x = view_screen_frame.origin.x + view_screen_frame.size.width - panel_width
        preferred_y = view_screen_frame.origin.y + view_screen_frame.size.height + 6.0
        if visible_frame is not None:
            min_x = visible_frame.origin.x + 6.0
            max_x = visible_frame.origin.x + visible_frame.size.width - panel_width - 6.0
            preferred_x = min(max(preferred_x, min_x), max_x if max_x >= min_x else min_x)
            max_y = visible_frame.origin.y + visible_frame.size.height - panel_height - 6.0
            if preferred_y > max_y:
                preferred_y = view_screen_frame.origin.y - panel_height - 6.0
        self._show(text, NSMakeRect(preferred_x, preferred_y, panel_width, panel_height), panel_width, panel_height)
        self.label.setUsesSingleLineMode_(False)
        self.label.setLineBreakMode_(NSLineBreakByWordWrapping)
        self.label.setAlignment_(0)
        self.label.setFrame_(
            NSMakeRect(
                self._horizontal_padding,
                self._vertical_padding,
                panel_width - self._horizontal_padding * 2.0,
                panel_height - self._vertical_padding * 2.0,
            )
        )
