"""Menu-bar client: same record/transcribe engine as client.py, but as a
rumps menu-bar app instead of a console window, with a small "recent
servers" list instead of hand-editing env vars.

macOS equivalent of tray_client.py (which is Windows-only: pystray,
winreg, tkinter). Settings (recent servers + their tokens) live in
~/Library/Application Support/KubunDictate/client_settings.json -- the
mac analogue of tray_client.py's %APPDATA% location. Run via
start_tray_mac.sh.

The global hotkey listener (pynput) needs TWO separate macOS
permissions, confirmed hands-on rather than assumed: Accessibility
(System Settings -> Privacy & Security -> Accessibility) silences
pynput's own internal trust check, but the actual event delivery goes
through CGEventTapCreate, which is gated independently by Input
Monitoring (Eingabeuberwachung in German) -- Accessibility alone was
not enough, the hotkey listener received zero events for any key until
Input Monitoring was also granted. Left alone, macOS does not reliably
auto-prompt for either on a plain venv Python process the way it does
for Microphone access, so we proactively call the prompting variant of
both underlying checks at startup (_request_accessibility_trust,
_request_input_monitoring_access) so macOS's native permission dialogs
show up on first launch instead of nothing happening. Neither call
retroactively grants the already-running process the permission,
though -- granting still requires quitting and relaunching once, same
as the manual flow in README.md.
"""

import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import rumps
from PIL import Image

try:
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
except ImportError:
    try:
        from Quartz import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    except ImportError:
        AXIsProcessTrustedWithOptions = None
        kAXTrustedCheckOptionPrompt = None

try:
    from Quartz import CGPreflightListenEventAccess, CGRequestListenEventAccess
except ImportError:
    CGPreflightListenEventAccess = None
    CGRequestListenEventAccess = None

import client
import mac_toast

MAX_RECENT = 3
ICON_DIR = Path(__file__).resolve().parent / "images"
ICON_SOURCE_SIZE = 48  # nearest pre-rendered size at/above ICON_RENDER_SIZE
ICON_RENDER_SIZE = 44  # @2x for a 22pt menu-bar icon
PULSE_INTERVAL = 0.7  # seconds between listening-a/listening-b swaps

SETTINGS_DIR = Path.home() / "Library" / "Application Support" / "KubunDictate"
SETTINGS_PATH = SETTINGS_DIR / "client_settings.json"

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCH_AGENT_LABEL = "com.kubundictate.trayclient"
LAUNCH_AGENT_PATH = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"


def _launch_agent_command():
    return [str(Path(sys.executable).resolve()), str(Path(__file__).resolve())]


def is_startup_enabled():
    return LAUNCH_AGENT_PATH.exists()


def set_startup_enabled(enabled):
    # Generated inline rather than checked in as a template file, mirroring
    # tray_client.py's inline winreg calls on Windows.
    if enabled:
        LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": _launch_agent_command(),
            "RunAtLoad": True,
        }
        with open(LAUNCH_AGENT_PATH, "wb") as f:
            plistlib.dump(plist, f)
        subprocess.run(["launchctl", "load", "-w", str(LAUNCH_AGENT_PATH)], check=False)
    else:
        subprocess.run(["launchctl", "unload", "-w", str(LAUNCH_AGENT_PATH)], check=False)
        try:
            LAUNCH_AGENT_PATH.unlink()
        except FileNotFoundError:
            pass


def load_recent():
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return [e for e in data.get("recent", []) if e.get("url")][:MAX_RECENT]


def save_recent(recent):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"recent": recent[:MAX_RECENT]}, indent=2), encoding="utf-8"
    )


def add_or_promote(recent, url, token):
    """Moves url to the front (with the given token), capped at MAX_RECENT."""
    recent = [e for e in recent if e["url"] != url]
    recent.insert(0, {"url": url, "token": token})
    return recent[:MAX_RECENT]


def normalize_url(addr):
    addr = addr.strip()
    if addr.startswith("http://") or addr.startswith("https://"):
        return addr
    if not re.search(r":\d+$", addr):
        addr = f"{addr}:50505"
    return f"http://{addr}"


def _request_accessibility_trust():
    # Triggers macOS's own native "would like to control this computer"
    # dialog on first launch instead of pynput's silent, log-only failure.
    # Doesn't grant the running process trust retroactively -- still needs
    # a quit + relaunch after the user grants it, same as the manual flow.
    if AXIsProcessTrustedWithOptions is None:
        return
    try:
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception:
        pass


def _request_input_monitoring_access():
    # Separate TCC category from Accessibility -- CGEventTapCreate (what
    # pynput's listener actually uses to receive key events) is gated on
    # this independently, confirmed hands-on: Accessibility trust alone
    # left the listener receiving zero events for any key. Same
    # prompt-then-relaunch caveat as _request_accessibility_trust.
    if CGRequestListenEventAccess is None:
        return
    try:
        if CGPreflightListenEventAccess is not None and CGPreflightListenEventAccess():
            return  # already granted
        CGRequestListenEventAccess()
    except Exception:
        pass


def _fill_frame(img, size):
    # The source PNGs carry a few px of transparent margin around the
    # glyph (design-grid padding). The OS fits the whole canvas -- margin
    # included -- into the menu-bar slot, so that margin is wasted space
    # the glyph could otherwise occupy. Crop to the visible pixels and
    # scale back up (aspect preserved) to reclaim it.
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    scale = min(size / img.width, size / img.height)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - new_size[0]) // 2, (size - new_size[1]) // 2), img)
    return canvas


def _make_icon_file(state):
    # rumps.App.icon wants a file path, not an in-memory image like
    # pystray accepts -- render once per state and swap paths instead.
    # Pre-rendered per state/size in images/ (see
    # kubundictate-icons/README.md); resize the nearest source size down
    # to the actual menu-bar render size instead of shipping a duplicate
    # 44px asset.
    src = ICON_DIR / f"kubundictate-{state}-{ICON_SOURCE_SIZE}.png"
    resized = _fill_frame(Image.open(src), ICON_RENDER_SIZE)
    fd, path = tempfile.mkstemp(suffix=".png", prefix="kubundictate_icon_")
    os.close(fd)
    resized.save(path)
    return path


def _current_icon_state(pulse_a):
    if client.is_transcribing():
        return "listening-a"  # held static while awaiting the server
    if client.is_recording():
        return "listening-a" if pulse_a else "listening-b"
    return "idle"


class TrayApp(rumps.App):
    def __init__(self):
        self.recent = load_recent()
        self.stop_event = threading.Event()
        self._icon_state = "idle"
        self._pulse_a = True
        self._last_pulse = time.monotonic()
        self._icon_paths = {
            state: _make_icon_file(state) for state in ("idle", "listening-a", "listening-b")
        }
        # quit_button=None so our own Quit item can set stop_event before
        # calling rumps.quit_application().
        super().__init__("KubunDictate", icon=self._icon_paths["idle"], quit_button=None)
        self._rebuild_menu()

        self._toast = mac_toast.Toast()
        self._toast_phase = None  # None | "listening" | "transcribing"
        self._toast_seen_seq = 0
        self._toast_hide_at = None

    def _apply_active(self):
        if self.recent:
            active = self.recent[0]
            client.settings.server_url = active["url"]
            client.settings.token = active["token"]

    def _rebuild_menu(self):
        items = []
        if self.recent:
            items.append(rumps.MenuItem(f"Server: {self.recent[0]['url']}"))
        else:
            items.append(rumps.MenuItem("No server configured"))
        items.append(rumps.separator)

        for entry in self.recent:
            item = rumps.MenuItem(entry["url"], callback=self._make_select_handler(entry))
            item.state = self.recent[0]["url"] == entry["url"]
            items.append(item)

        items.append(rumps.MenuItem("Enter new server...", callback=self._on_new_server))
        items.append(rumps.separator)

        startup_item = rumps.MenuItem("Run at login", callback=self._on_toggle_startup)
        startup_item.state = is_startup_enabled()
        items.append(startup_item)

        items.append(rumps.MenuItem("Quit", callback=self._on_quit))
        self.menu = items

    def _prompt_for_server(self, initial_token=""):
        resp = rumps.Window(
            message="Server address, e.g. 192.168.1.50:50505 or a Tailscale IP:",
            title="KubunDictate",
            ok="Next",
            cancel="Cancel",
        ).run()
        if not resp.clicked or not resp.text.strip():
            return None
        url = normalize_url(resp.text)

        resp = rumps.Window(
            message="Shared token (blank = none):",
            title="KubunDictate",
            default_text=initial_token or "",
            ok="Save",
            cancel="Cancel",
        ).run()
        if not resp.clicked:
            return None
        return {"url": url, "token": resp.text.strip() or None}

    def _make_select_handler(self, entry):
        def handler(sender):
            self.recent = add_or_promote(self.recent, entry["url"], entry["token"])
            save_recent(self.recent)
            self._apply_active()
            self._rebuild_menu()

        return handler

    def _on_new_server(self, sender):
        current_token = self.recent[0]["token"] if self.recent else ""
        result = self._prompt_for_server(initial_token=current_token)
        if not result:
            return
        self.recent = add_or_promote(self.recent, result["url"], result["token"])
        save_recent(self.recent)
        self._apply_active()
        self._rebuild_menu()

    def _on_toggle_startup(self, sender):
        set_startup_enabled(not is_startup_enabled())
        self._rebuild_menu()

    def _on_quit(self, sender):
        self.stop_event.set()
        rumps.quit_application()

    def _check_recording(self, _timer):
        # Runs on the main run loop (rumps.Timer), not a background thread
        # -- AppKit property updates like self.icon need the main thread.
        now = time.monotonic()
        if now - self._last_pulse >= PULSE_INTERVAL:
            self._pulse_a = not self._pulse_a
            self._last_pulse = now
        state = _current_icon_state(self._pulse_a)
        if state != self._icon_state:
            self._icon_state = state
            self.icon = self._icon_paths[state]

        self._update_toast(now)

    def _update_toast(self, now):
        if client.is_recording():
            phase = "listening"
        elif client.is_transcribing():
            phase = "transcribing"
        else:
            phase = None

        if phase != self._toast_phase:
            if phase == "listening":
                self._toast.show_listening()
                self._toast_hide_at = None
            elif phase == "transcribing":
                self._toast.show_transcribing()
                self._toast_hide_at = None
            self._toast_phase = phase
        elif phase == "listening":
            self._toast.set_pulse_frame(self._pulse_a)

        result = client.last_result
        if result and result[2] != self._toast_seen_seq:
            self._toast_seen_seq = result[2]
            error = result[1]
            # "aborted" (clip too short / no audio) isn't a real attempt
            # worth a message -- just clear whatever's showing.
            if error == "aborted":
                self._toast.hide()
            else:
                self._toast.show_result(error)
                self._toast_hide_at = now + 1.0
            self._toast_phase = None

        if self._toast_hide_at is not None and now >= self._toast_hide_at:
            self._toast.hide()
            self._toast_hide_at = None

    def run(self):
        first_run = not self.recent
        if first_run:
            result = self._prompt_for_server()
            if not result:
                return
            self.recent = add_or_promote(self.recent, result["url"], result["token"])
            save_recent(self.recent)
            self._rebuild_menu()
        self._apply_active()

        threading.Thread(target=lambda: client.run(self.stop_event), daemon=True).start()
        rumps.Timer(self._check_recording, 0.15).start()

        super().run()


def main():
    _request_accessibility_trust()
    _request_input_monitoring_access()
    TrayApp().run()


if __name__ == "__main__":
    main()
