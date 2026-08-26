"""Always-on-top, non-activating recording/result toast for the macOS
menu-bar client (#16).

Unlike win_toast.py (Windows has no existing continuously-pumped main
loop that pystray/Tkinter can safely share, so that toast gets its own
thread and message loop), this rides the same AppKit run loop
rumps.App.run() already owns -- no new thread, no cross-thread
marshaling. Driven by tray_client_mac.py's existing 0.15s rumps.Timer
poll (the one that already updates the menu-bar icon color), not a
callback.

Shown via orderFrontRegardless() rather than makeKeyAndOrderFront_() --
the standard non-activating-overlay technique on macOS (same family as
the volume/brightness HUD), so it never steals focus from whatever
window the user is dictating into.
"""

from pathlib import Path

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSImage,
    NSImageView,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)

ICON_DIR = Path(__file__).resolve().parent / "icons"
ICON_SOURCE_SIZE = 64
ICON_DISPLAY_SIZE = 32
PANEL_HEIGHT = 56
PANEL_WIDTH = 260
ICON_MARGIN = 14
TOP_MARGIN = 8

MESSAGES = {
    "listening-a": "Listening...",
    "listening-b": "Listening...",
    "transcribing": "Transcribing...",
    "copied": "Copied to clipboard",
    "no-speech": "No speech detected",
    "error": "Couldn't reach server",
}
ICON_FOR_STATE = {
    "listening-a": "listening-a",
    "listening-b": "listening-b",
    # Held static (no pulse), same convention as the menu-bar icon itself
    # (_current_icon_state) while awaiting the server's response.
    "transcribing": "listening-a",
    "copied": "idle",
    "no-speech": "idle",
    "error": "idle",
}


class Toast:
    def __init__(self):
        self._images = {
            state: NSImage.alloc().initWithContentsOfFile_(
                str(ICON_DIR / f"kubundictate-{state}-{ICON_SOURCE_SIZE}.png")
            )
            for state in ("idle", "listening-a", "listening-b")
        }

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        )

        content = panel.contentView()
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.11, 0.92).CGColor())
        content.layer().setCornerRadius_(PANEL_HEIGHT / 2)

        icon_rect = NSMakeRect(
            ICON_MARGIN, (PANEL_HEIGHT - ICON_DISPLAY_SIZE) / 2, ICON_DISPLAY_SIZE, ICON_DISPLAY_SIZE
        )
        self._image_view = NSImageView.alloc().initWithFrame_(icon_rect)
        content.addSubview_(self._image_view)

        label_x = ICON_MARGIN * 2 + ICON_DISPLAY_SIZE
        label_rect = NSMakeRect(label_x, 0, PANEL_WIDTH - label_x - ICON_MARGIN, PANEL_HEIGHT)
        self._label = NSTextField.alloc().initWithFrame_(label_rect)
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.94, 1.0))
        self._label.setFont_(NSFont.systemFontOfSize_(13))
        content.addSubview_(self._label)

        self._panel = panel

    def show_listening(self):
        self._set_state("listening-a")

    def show_transcribing(self):
        self._set_state("transcribing")

    def set_pulse_frame(self, pulse_a):
        # Called on every poll tick while listening -- see
        # tray_client_mac.py's _update_toast, which already tracks the
        # same pulse phase used for the menu-bar icon.
        self._set_state("listening-a" if pulse_a else "listening-b")

    def show_result(self, error):
        state = {"no-speech": "no-speech", "could not reach server": "error"}.get(error, "copied")
        self._set_state(state)

    def hide(self):
        self._panel.orderOut_(None)

    def _set_state(self, state):
        self._image_view.setImage_(self._images[ICON_FOR_STATE[state]])
        self._label.setStringValue_(MESSAGES[state])
        self._position()
        self._panel.orderFrontRegardless()

    def _position(self):
        screen = self._panel.screen() or NSScreen.mainScreen()
        if screen is None:
            return
        visible = screen.visibleFrame()  # excludes the menu bar and a docked Dock
        x = visible.origin.x + (visible.size.width - PANEL_WIDTH) / 2
        y = visible.origin.y + visible.size.height - PANEL_HEIGHT - TOP_MARGIN
        self._panel.setFrameOrigin_((x, y))
