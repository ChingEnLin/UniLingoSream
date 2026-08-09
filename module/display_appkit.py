""" AppKit (pyobjc) prototype of the subtitle overlay.

Drop-in alternative to module/display.py's DisplayTranslation, exposing the same
surface main.py touches: update_label(text), start_gui(), and root.after(ms, fn, *args).

Why this exists (improvement-spec item 16): Tkinter cannot do click-through or float
over macOS native-fullscreen apps. A native NSPanel can:
  - setIgnoresMouseEvents_(True)          -> true click-through (spec item 10)
  - collectionBehavior CanJoinAllSpaces | FullScreenAuxiliary | Stationary
                                          -> shows over green-button fullscreen, every Space
  - NSWindowStyleMaskNonactivatingPanel   -> never steals focus from the video
  - NSScreenSaverWindowLevel              -> sits above fullscreen windows

macOS only. Requires: pip install pyobjc-framework-Cocoa
Run standalone to eval:  python -m module.display_appkit         (shows a demo overlay)
Self-check (no GUI):     python -m module.display_appkit --check
"""

import json
import os
import logging

import objc

from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSPanel, NSView,
    NSTextField, NSColor, NSFont, NSScreen, NSMenu, NSMenuItem, NSStatusBar,
    NSSlider, NSEventTypeLeftMouseUp,
    NSBackingStoreBuffered, NSTextAlignmentCenter, NSLineBreakByWordWrapping,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSScreenSaverWindowLevel, NSVariableStatusItemLength,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)
from Foundation import NSObject, NSTimer, NSMakeRect
from PyObjCTools import AppHelper

from module.utility.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_UI_CONFIG = {
    "font_family": "Helvetica",
    "font_size": 28,
    "text_color": "#FFFFFF",
    "bg_color": "#000000",
    "bg_opacity": 0.6,
    "window_height": 90,
    "window_width_percent": 80,
    "bottom_margin": 100,
    "always_on_top": True,
    "click_through": True,   # the whole point of moving off Tk; set False to drag the bar
    "grow_up": True,         # False: anchor the top edge, so a bar near the top grows downward
}

CONTEXTS_DIR = "contexts"


def _nscolor(hex_str, alpha=1.0):
    """ '#RRGGBB' -> NSColor. """
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


class _RunLoopShim:
    """ Provides main.py's `display.root.after(ms, fn, *args)` on the AppKit run loop.

    Tk's after() schedules a one-shot callback on the GUI loop; poll_transcription
    reschedules itself each tick. NSTimer gives the same one-shot-on-main-thread behavior.
    Plain Python object (not NSObject): it is never passed across the ObjC bridge.
    """
    def after(self, ms, fn, *args):
        # ponytail: block runs on the main run loop, so UI mutations here are thread-safe.
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            ms / 1000.0, False, lambda _timer: fn(*args)
        )


class _Controller(NSObject):
    """ Menu-item target. Must be an ObjC object to receive the action selector. """
    def initWithDisplay_(self, display):
        self = objc.super(_Controller, self).init()
        if self is None:
            return None
        self._display = display
        return self

    def toggleMove_(self, sender):
        """ Click-through and drag are mutually exclusive on one window, so toggle between
        them: unlock to drag the bar, lock to restore click-through (and save position). """
        d = self._display
        if d.panel.ignoresMouseEvents():          # locked / click-through -> unlock to move
            d.panel.setIgnoresMouseEvents_(False)
            d.panel.setMovableByWindowBackground_(True)
            sender.setTitle_("Lock bar (restore click-through)")
        else:                                     # moving -> lock and persist
            d.panel.setIgnoresMouseEvents_(True)
            d.panel.setMovableByWindowBackground_(False)
            sender.setTitle_("Move bar")
            d._persist_position()

    def fontSlider_(self, sender):
        """ Resize live while dragging; persist to config only when the drag ends. """
        d = self._display
        d.set_font_size(sender.doubleValue(), persist=False)
        event = NSApplication.sharedApplication().currentEvent()
        if event is not None and event.type() == NSEventTypeLeftMouseUp:
            d._persist("ui", {"font_size": d._font_size})

    def chooseContext_(self, sender):
        self._display.set_context(sender.representedObject())

    def recenter_(self, sender):
        self._display.move_to(sender.representedObject() == "top")

    def toggleGrowUp_(self, sender):
        """ Flip which edge stays put when the bar resizes (ui.grow_up). """
        d = self._display
        grow_up = not d.config["grow_up"]
        d.config["grow_up"] = grow_up
        sender.setState_(1 if grow_up else 0)
        d._persist("ui", {"grow_up": grow_up})


class DisplayTranslation:
    """ NSPanel subtitle overlay. Same interface as display.DisplayTranslation. """

    def __init__(self, config_path="config.json", config=None):
        self.config_path = config_path
        # Set by main.py to TranscriberTranslator.set_context_file; the menu is inert without it.
        self.on_context_change = None
        self.config = DEFAULT_UI_CONFIG.copy()
        if config is not None:
            self.config.update(config)
        else:
            self.config.update(load_config(config_path).get("ui", {}))

        app = NSApplication.sharedApplication()  # must exist before any window
        # Accessory policy (no dock icon) must be set BEFORE creating the status item,
        # or macOS may create it under the default no-UI policy and never draw it.
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        screen = NSScreen.mainScreen().frame()
        self._width = int(screen.size.width * self.config["window_width_percent"] / 100)
        self._height = self.config["window_height"]
        x, y = self._resolve_origin(screen)

        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self._width, self._height),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setLevel_(NSScreenSaverWindowLevel)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setIgnoresMouseEvents_(bool(self.config["click_through"]))
        # ponytail: drag by background instead of subclassing NSView for mouseDragged.
        # Position is persisted when the bar is locked again (see _Controller.toggleMove_).
        self.panel.setMovableByWindowBackground_(not self.config["click_through"])

        # Rounded translucent background layer
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self._width, self._height))
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(
            _nscolor(self.config["bg_color"], self.config["bg_opacity"]).CGColor()
        )
        content.layer().setCornerRadius_(12.0)
        self.panel.setContentView_(content)

        self.field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(20, 10, self._width - 40, self._height - 20)
        )
        self.field.setStringValue_("Waiting for translation...")
        self.field.setBezeled_(False)
        self.field.setDrawsBackground_(False)
        self.field.setEditable_(False)
        self.field.setSelectable_(False)
        self.field.setAlignment_(NSTextAlignmentCenter)
        self.field.setTextColor_(_nscolor(self.config["text_color"]))
        self._font_family = self.config["font_family"]
        self._font_size = self.config["font_size"]
        self._apply_font()
        self.field.setUsesSingleLineMode_(False)
        self.field.cell().setWraps_(True)
        self.field.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        content.addSubview_(self.field)

        # Quit control that works even under click-through: a menu-bar status item.
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._status_item.button().setTitle_("UL")
        menu = NSMenu.alloc().init()
        self._controller = _Controller.alloc().initWithDisplay_(self)
        move_title = "Move bar" if self.config["click_through"] else "Lock bar (restore click-through)"
        move_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            move_title, "toggleMove:", "m"
        )
        move_item.setTarget_(self._controller)
        menu.addItem_(move_item)

        self._grow_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Grow upward", "toggleGrowUp:", ""
        )
        self._grow_item.setTarget_(self._controller)
        self._grow_item.setState_(1 if self.config["grow_up"] else 0)
        menu.addItem_(self._grow_item)

        position_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Position", None, ""
        )
        menu.addItem_(position_item)
        menu.setSubmenu_forItem_(self._build_position_menu(), position_item)

        context_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Context", None, ""
        )
        menu.addItem_(context_item)
        menu.setSubmenu_forItem_(self._build_context_menu(), context_item)

        # Font-size slider embedded as a custom menu-item view (drag instead of clicking).
        slider_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 220, 34))
        slider_label = NSTextField.alloc().initWithFrame_(NSMakeRect(14, 7, 46, 20))
        slider_label.setStringValue_("Font")
        slider_label.setBezeled_(False)
        slider_label.setDrawsBackground_(False)
        slider_label.setEditable_(False)
        slider_label.setSelectable_(False)
        slider_view.addSubview_(slider_label)
        self._font_slider = NSSlider.alloc().initWithFrame_(NSMakeRect(58, 4, 150, 26))
        self._font_slider.setMinValue_(12.0)
        self._font_slider.setMaxValue_(96.0)
        self._font_slider.setDoubleValue_(float(self._font_size))
        self._font_slider.setContinuous_(True)
        self._font_slider.setTarget_(self._controller)
        self._font_slider.setAction_("fontSlider:")
        slider_view.addSubview_(self._font_slider)
        font_item = NSMenuItem.alloc().init()
        font_item.setView_(slider_view)
        menu.addItem_(font_item)

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit UniLingoStream", "terminate:", "q"
        )
        menu.addItem_(quit_item)
        self._status_item.setMenu_(menu)

        self.root = _RunLoopShim()

    def _build_context_menu(self):
        """ Submenu of contexts/*.json plus "None"; the active one carries the checkmark. """
        active = load_config(self.config_path).get("api", {}).get("context_file") or ""
        paths = [""]
        if os.path.isdir(CONTEXTS_DIR):
            paths += sorted(os.path.join(CONTEXTS_DIR, f)
                            for f in os.listdir(CONTEXTS_DIR) if f.endswith(".json"))

        submenu = NSMenu.alloc().init()
        self._context_items = []
        for path in paths:
            title = os.path.basename(path)[:-len(".json")].replace("_", " ") if path else "None"
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "chooseContext:", ""
            )
            item.setTarget_(self._controller)
            item.setRepresentedObject_(path)
            item.setState_(1 if path == active else 0)
            submenu.addItem_(item)
            self._context_items.append(item)
        return submenu

    def _build_position_menu(self):
        """ Submenu of screen anchors, same shape as the context list. Nothing is checked
        until one is picked: the bar starts wherever it was last dragged. """
        submenu = NSMenu.alloc().init()
        self._position_items = {}
        for title, where in (("Centered top", "top"), ("Centered bottom", "bottom")):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "recenter:", ""
            )
            item.setTarget_(self._controller)
            item.setRepresentedObject_(where)
            submenu.addItem_(item)
            self._position_items[where] = item
        return submenu

    def move_to(self, top):
        """ Re-center the bar on the active screen, snapped to its top or bottom edge.

        The rescue hatch for a bar stranded off-screen: a window_x/window_y saved on an
        external monitor can land outside every attached display once it is unplugged.
        Width is recomputed here too, since the new screen may be a different size.
        """
        screen = NSScreen.mainScreen().visibleFrame()   # excludes menu bar and Dock
        self._width = int(screen.size.width * self.config["window_width_percent"] / 100)
        height = self.panel.frame().size.height
        margin = self.config["bottom_margin"]
        x = screen.origin.x + (screen.size.width - self._width) / 2
        if top:
            y = screen.origin.y + screen.size.height - height - margin
        else:
            y = screen.origin.y + margin
        self.panel.setFrame_display_(NSMakeRect(x, y, self._width, height), True)
        self.field.setFrame_(NSMakeRect(20, 10, self._width - 40, height - 20))

        for where, item in self._position_items.items():
            item.setState_(1 if where == ("top" if top else "bottom") else 0)

        # A bar at the top has to grow downward, or long lines climb off the screen.
        self.config["grow_up"] = not top
        self._grow_item.setState_(0 if top else 1)
        self._persist("ui", {"grow_up": not top})
        self._persist_position()

    def set_context(self, path):
        """ Switch the translation context live and remember it in config.json. """
        for item in self._context_items:
            item.setState_(1 if item.representedObject() == path else 0)
        self._persist("api", {"context_file": path})
        if self.on_context_change:
            self.on_context_change(path)

    def _resolve_origin(self, screen):
        """ Bottom-left origin (AppKit). Centered above bottom_margin unless config pins it.

        window_x/window_y persisted by the Tk build are top-left; convert y if present.
        """
        x = self.config.get("window_x")
        if x is None:
            x = (screen.size.width - self._width) // 2
        tk_y = self.config.get("window_y")
        if tk_y is None:
            y = self.config["bottom_margin"]
        else:
            y = screen.size.height - tk_y - self._height
        return x, y

    def _apply_font(self):
        font = NSFont.fontWithName_size_(self._font_family, self._font_size) \
            or NSFont.systemFontOfSize_(self._font_size)
        self.field.setFont_(font)

    def set_font_size(self, size, persist=True):
        """ Live font-size change; clamped, and persisted to config unless persist=False. """
        self._font_size = max(12, min(int(size), 96))
        self._apply_font()
        self.update_label(self.field.stringValue())  # re-fit height for the new size
        if persist:
            self._persist("ui", {"font_size": self._font_size})

    def _persist(self, section, values):
        """ Merge values into one section of config.json. """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault(section, {}).update(values)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Could not persist %s settings: %s", section, e)

    def _persist_position(self):
        """ Save current position as top-left window_x/window_y (matches _resolve_origin
        and the Tk backend's convention). """
        frame = self.panel.frame()
        screen_h = NSScreen.mainScreen().frame().size.height
        self._persist("ui", {
            "window_x": int(frame.origin.x),
            "window_y": int(screen_h - frame.origin.y - frame.size.height),
        })

    def update_label(self, text):
        """ Set text and grow height to fit, anchoring the bottom edge (ui.grow_up, default)
        or the top edge (grow_up false, for a bar parked at the top of the screen). """
        self.field.setStringValue_(text)
        bounds = NSMakeRect(0, 0, self._width - 40, 10000)
        needed = int(self.field.cell().cellSizeForBounds_(bounds).height) + 20
        base = self.config["window_height"]
        # ponytail: cap on a share of the screen, not on window_height * 3 - that base is a
        # single-line height for the default font, so a large font_size clipped wrapped lines.
        cap = int(NSScreen.mainScreen().frame().size.height * 0.4)
        height = max(base, min(needed, cap))
        frame = self.panel.frame()
        if int(frame.size.height) != height:
            # bottom-left origin: keeping origin.y grows upward, keeping the top edge
            # (origin.y + size.height) grows downward - the useful one near the screen top.
            y = frame.origin.y
            if not self.config["grow_up"]:
                y += frame.size.height - height
            self.panel.setFrame_display_(
                NSMakeRect(frame.origin.x, y, self._width, height), True
            )
            self.field.setFrame_(NSMakeRect(20, 10, self._width - 40, height - 20))

    def start_gui(self):
        """ Show the overlay and run the AppKit event loop (blocks like Tk mainloop). """
        self.panel.orderFrontRegardless()
        AppHelper.runEventLoop(installInterrupt=True)  # Ctrl+C quits cleanly


def _selfcheck():
    """ Non-GUI checks on the parsing/geometry logic. """
    c = _nscolor("#FFFFFF")
    assert abs(c.redComponent() - 1.0) < 1e-6, "white should parse to r=1.0"
    c2 = _nscolor("#000000", 0.6)
    assert abs(c2.alphaComponent() - 0.6) < 1e-6, "alpha not applied"
    c3 = _nscolor("#3366CC")
    assert abs(c3.greenComponent() - 0x66 / 255.0) < 1e-6, "hex green wrong"

    # bottom-left origin math: a Tk top-left window_y must flip about screen height
    class _S:
        class size:
            width = 1000
            height = 800
    d = DisplayTranslation.__new__(DisplayTranslation)
    d.config = {**DEFAULT_UI_CONFIG, "window_x": None, "window_y": 100}
    d._width, d._height = 800, 90
    x, y = d._resolve_origin(_S)
    assert x == (1000 - 800) // 2, "x should center when unset"
    assert y == 800 - 100 - 90, "tk top-left y not converted to appkit bottom-left"

    # Live font-size clamp (constructs a real panel; persists to a throwaway config)
    import tempfile
    tmp = tempfile.mktemp(suffix=".json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ui": {}}, f)
    d2 = DisplayTranslation(config={})
    d2.config_path = tmp
    d2.set_font_size(1000)
    assert d2._font_size == 96, "font size not clamped to max"
    d2.set_font_size(1)
    assert d2._font_size == 12, "font size not clamped to min"

    # A wrapped line must never render outside the text field (the base*3 cap clipped
    # the third line once font_size grew past window_height / 3).
    d3 = DisplayTranslation(config={"font_size": 57, "window_height": 70})
    d3.update_label("這是一段很長的字幕測試文字，用來確認字幕列會不會長到三行，"
                    "並且第三行是不是會被裁掉看不到，這樣才能重現使用者報告的問題。")
    text_h = d3.field.cell().cellSizeForBounds_(
        NSMakeRect(0, 0, d3._width - 40, 10000)
    ).height
    assert d3.field.frame().size.height >= text_h, \
        f"text ({text_h}) clipped by field ({d3.field.frame().size.height})"

    # grow_up=False must hold the top edge still and extend downward instead.
    d4 = DisplayTranslation(config={"font_size": 57, "window_height": 70, "grow_up": False})
    before = d4.panel.frame()
    top = before.origin.y + before.size.height
    d4.update_label("這是一段很長的字幕測試文字，用來確認字幕列會不會往下長而不是往上長，"
                    "放在畫面上方時才不會蓋掉上面的內容。")
    after = d4.panel.frame()
    assert after.size.height > before.size.height, "window did not grow at all"
    assert abs((after.origin.y + after.size.height) - top) < 1, \
        "top edge moved: window grew upward despite grow_up=False"

    # Menu: the Context submenu offers None + every contexts/*.json, choosing one forwards
    # the path to the transcriber, and the grow toggle flips ui.grow_up.
    d5 = DisplayTranslation(config={"grow_up": True})
    d5.config_path = tmp
    titles = [i.title() for i in d5._context_items]
    assert titles[0] == "None", "context menu must offer a no-context option"
    on_disk = sum(1 for f in os.listdir(CONTEXTS_DIR) if f.endswith(".json")) \
        if os.path.isdir(CONTEXTS_DIR) else 0
    assert len(titles) == on_disk + 1, f"context menu {titles} does not match {CONTEXTS_DIR}/"
    switched = []
    d5.on_context_change = switched.append
    d5._controller.chooseContext_(d5._context_items[-1])
    assert switched == [d5._context_items[-1].representedObject()], "context choice not forwarded"
    assert d5._context_items[-1].state() == 1 and d5._context_items[0].state() == 0, \
        "checkmark did not follow the chosen context"
    d5._controller.toggleGrowUp_(d5._grow_item)
    assert d5.config["grow_up"] is False, "grow toggle did not flip grow_up"
    with open(tmp, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["ui"]["grow_up"] is False and "context_file" in saved["api"], \
        f"menu choices not persisted: {saved}"

    # Rescue: a bar stranded off-screen (unplugged monitor) must come back onto the
    # active screen, centered and inside the visible frame, whichever edge is asked for.
    d6 = DisplayTranslation(config={"grow_up": True})
    d6.config_path = tmp
    d6.panel.setFrame_display_(NSMakeRect(-9000, -9000, 400, 70), False)
    assert [i.state() for i in d6._position_items.values()] == [0, 0], \
        "no anchor should be checked before one is picked"
    d6._controller.recenter_(d6._position_items["top"])
    vis = NSScreen.mainScreen().visibleFrame()
    f = d6.panel.frame()
    assert abs((f.origin.x + f.size.width / 2) - (vis.origin.x + vis.size.width / 2)) < 1, \
        f"bar {f} not horizontally centered on the active screen {vis}"
    assert vis.origin.y <= f.origin.y and f.origin.y + f.size.height <= vis.origin.y + vis.size.height, \
        f"bar {f} landed outside the visible frame {vis}"
    assert d6.config["grow_up"] is False, "a top-aligned bar must grow downward"
    assert d6._position_items["top"].state() == 1, "picked anchor not checked"
    d6._controller.recenter_(d6._position_items["bottom"])
    assert d6._position_items["top"].state() == 0, "checkmark did not follow the new anchor"
    assert abs(d6.panel.frame().origin.y - (vis.origin.y + d6.config["bottom_margin"])) < 1, \
        "bottom alignment ignored bottom_margin"
    assert d6.config["grow_up"] is True, "a bottom-aligned bar must grow upward"

    os.remove(tmp)
    print("display_appkit self-check passed")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        _selfcheck()
        sys.exit(0)

    # Demo: rotate fake subtitles so the overlay can be evaluated without the pipeline.
    demo = DisplayTranslation()
    _lines = [
        "Listening...",
        "サトシ、いくぞ！  (Satoshi, let's go!)",
        "This is a much longer line to check that the subtitle bar grows upward "
        "to fit two or three wrapped lines without clipping the text at the bottom.",
        "ピカチュウ！  (Pikachu!)",
    ]
    _i = {"n": 0}

    def _tick():
        demo.update_label(_lines[_i["n"] % len(_lines)])
        _i["n"] += 1
        demo.root.after(1800, _tick)

    demo.root.after(300, _tick)
    print("Showing demo overlay. Quit via the 'UL' menu-bar item or Ctrl+C.")
    demo.start_gui()
