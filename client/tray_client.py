"""System-tray client: same record/transcribe engine as client.py, but as
a tray icon instead of a console window, with a named list of servers to
switch between (typically a LAN address and a Tailscale one).

Servers live in %APPDATA%\\KubunDictate\\client_settings.json -- written
by the installer, editable straight from the tray menu, and separate from
the server's config.bat since this is meant to run standalone (no repo
folder needed once it's set up). The client deliberately has no
text-entry dialog of its own; see TrayApp._on_edit_servers for why. Run
via windows\\start_tray.bat (pythonw.exe, no console window).
"""

import ctypes
import json
import os
import re
import sys
import threading
import time
import traceback
import winreg
from pathlib import Path

from PIL import Image
import pystray

import client
import win_toast

# Assumed when an address is written without one. Matches the port
# server\install.ps1 offers by default.
DEFAULT_PORT = 9505
ICON_DIR = Path(__file__).resolve().parent / "icons"
ICON_SIZE = 64  # matches icons/kubundictate-<state>-64.png
PULSE_INTERVAL = 0.7  # seconds between listening-a/listening-b swaps

SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "KubunDictate"
SETTINGS_PATH = SETTINGS_DIR / "client_settings.json"
LOG_PATH = SETTINGS_DIR / "client.log"

STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "KubunDictate"


def log(message, exc=False):
    """Append a line to the client log, optionally with a traceback.

    This runs under pythonw.exe, which has no console and no stderr, so
    an exception raised inside a tray menu callback disappears without a
    trace -- the symptom is a menu item that simply does nothing. pystray
    swallows callback errors into its own logger too. Writing here means
    there is always somewhere to look.
    """
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
            if exc:
                traceback.print_exc(file=fh)
    except OSError:
        pass


def _startup_command():
    # Always the no-console pythonw.exe, regardless of which interpreter
    # launched this process (testing via python.exe shouldn't register a
    # console-window startup entry).
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve()
    return f'"{pythonw}" "{script}"'


def is_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_NAME)
    except FileNotFoundError:
        return False
    return value == _startup_command()


def set_startup_enabled(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, STARTUP_NAME)
            except FileNotFoundError:
                pass


def load_settings():
    """Reads the settings file, returning (servers, active_name).

    Written to tolerate hand editing, since that file is now the way
    servers get added or changed: entries without a name get one, bare
    addresses are expanded to full URLs, and blank entries are dropped.
    Also migrates the older {"recent": [...]} shape, which had no names
    and tracked the active server by keeping it first in the list.
    """
    # utf-8-sig, not utf-8: both Notepad (which "Edit servers..." opens
    # this in) and Windows PowerShell's Set-Content write UTF-8 with a
    # byte-order mark, and a plain utf-8 read rejects that outright. The
    # -sig codec strips a BOM when present and is identical otherwise.
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return [], None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        # Worth a log line: an unreadable file otherwise looks exactly
        # like "no servers configured", which is a maddening thing to
        # debug from the menu alone.
        log(f"could not read {SETTINGS_PATH}: {exc}")
        return [], None

    raw = data.get("servers")
    migrated = raw is None
    if migrated:
        raw = data.get("recent", [])

    servers = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or "").strip()
        if not url:
            continue
        servers.append(
            {
                "name": (entry.get("name") or "").strip() or f"Server {index + 1}",
                "url": normalize_url(url),
                "token": entry.get("token") or None,
            }
        )

    active = None if migrated else data.get("active")
    if not any(s["name"] == active for s in servers):
        active = servers[0]["name"] if servers else None
    return servers, active


def save_settings(servers, active):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"servers": servers, "active": active}, indent=2),
        encoding="utf-8",
    )


def normalize_url(addr):
    addr = addr.strip()
    if addr.startswith("http://") or addr.startswith("https://"):
        return addr
    if not re.search(r":\d+$", addr):
        addr = f"{addr}:{DEFAULT_PORT}"
    return f"http://{addr}"


def display_url(url):
    """Strips the scheme back off for editing, so the prefilled address
    reads the way the user typed it rather than the way we stored it."""
    prefix = "http://"
    return url[len(prefix):] if url.startswith(prefix) else url


def _fill_frame(img, size):
    # The source PNGs carry a few px of transparent margin around the
    # glyph (design-grid padding). The OS fits the whole canvas -- margin
    # included -- into the tray/menu-bar slot, so that margin is wasted
    # space the glyph could otherwise occupy. Crop to the visible pixels
    # and scale back up (aspect preserved) to reclaim it.
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


def _load_icons():
    # pystray.Icon.icon accepts a PIL Image directly -- no temp-file dance
    # needed, unlike the mac client's rumps.App.icon. Pre-rendered per
    # state/size in icons/ (see kubundictate-icons/README.md).
    return {
        state: _fill_frame(Image.open(ICON_DIR / f"kubundictate-{state}-{ICON_SIZE}.png"), ICON_SIZE)
        for state in ("idle", "listening-a", "listening-b")
    }


def _current_icon_state(pulse_a):
    if client.is_transcribing():
        return "listening-a"  # held static while awaiting the server
    if client.is_recording():
        return "listening-a" if pulse_a else "listening-b"
    return "idle"


def _watch_toast(toast, stop_event):
    # A separate poll from _watch_recording (not merged in) since the toast
    # tracks activity + result transitions, not the tray icon's pulse phase
    # -- win_toast.Toast owns its own pulse timer once shown.
    last_phase = None  # None | "listening" | "transcribing"
    seen_seq = 0
    while not stop_event.is_set():
        if client.is_recording():
            phase = "listening"
        elif client.is_transcribing():
            phase = "transcribing"
        else:
            phase = None

        if phase != last_phase:
            if phase == "listening":
                toast.show_listening()
            elif phase == "transcribing":
                toast.show_transcribing()
            last_phase = phase

        result = client.last_result
        if result and result[2] != seen_seq:
            seen_seq = result[2]
            error = result[1]
            # "aborted" (clip too short / no audio) isn't a real attempt
            # worth a message -- just clear whatever's showing.
            if error == "aborted":
                toast.hide()
            else:
                toast.show_result(error)
            last_phase = None
        time.sleep(0.05)


def _watch_recording(icon, icons, stop_event):
    last_state = None
    pulse_a = True
    last_pulse = time.monotonic()
    while not stop_event.is_set():
        now = time.monotonic()
        if now - last_pulse >= PULSE_INTERVAL:
            pulse_a = not pulse_a
            last_pulse = now
        state = _current_icon_state(pulse_a)
        if state != last_state:
            icon.icon = icons[state]
            last_state = state
        time.sleep(0.1)


class TrayApp:
    def __init__(self):
        self.servers, self.active = load_settings()
        self.stop_event = threading.Event()
        self._icons = _load_icons()
        self.icon = pystray.Icon(
            "kubundictate",
            icon=self._icons["idle"],
            title="KubunDictate",
            menu=self._build_menu(),
        )

    def _active_entry(self):
        for entry in self.servers:
            if entry["name"] == self.active:
                return entry
        return None

    def _apply_active(self):
        entry = self._active_entry()
        if entry:
            client.settings.server_url = entry["url"]
            client.settings.token = entry["token"]

    def _refresh_menu(self):
        self.icon.menu = self._build_menu()

    def _build_menu(self):
        items = []
        active = self._active_entry()
        if active:
            items.append(pystray.MenuItem(f"Using: {active['name']}", None, enabled=False))
        else:
            items.append(
                pystray.MenuItem("No server set up -- see Edit servers...", None, enabled=False)
            )
        items.append(pystray.Menu.SEPARATOR)

        for entry in self.servers:
            items.append(
                pystray.MenuItem(
                    f"{entry['name']}  ({display_url(entry['url'])})",
                    self._make_select_handler(entry),
                    checked=self._make_checked(entry),
                    radio=True,
                )
            )
        if self.servers:
            items.append(pystray.Menu.SEPARATOR)

        items.append(pystray.MenuItem("Edit servers...", self._on_edit_servers))
        items.append(pystray.MenuItem("Reload servers", self._on_reload))
        items.append(pystray.Menu.SEPARATOR)
        items.append(
            pystray.MenuItem(
                "Run at startup", self._on_toggle_startup, checked=lambda item: is_startup_enabled()
            )
        )
        items.append(pystray.MenuItem("Quit", self._on_quit))
        return pystray.Menu(*items)

    def _make_select_handler(self, entry):
        def handler(icon, item):
            try:
                self.active = entry["name"]
                save_settings(self.servers, self.active)
                self._apply_active()
                self._refresh_menu()
            except Exception:
                log(f"switching to server {entry['name']!r} failed", exc=True)

        return handler

    def _make_checked(self, entry):
        def checked(item):
            return entry["name"] == self.active

        return checked

    def _on_edit_servers(self, icon, item):
        # Hands the file to whatever opens .json (Notepad by default)
        # rather than showing a text box of our own. A Tk dialog opened
        # from a pystray menu callback could not be made to reliably take
        # keyboard focus -- the menu callback runs inside pystray's own
        # message loop, and every workaround traded one failure for
        # another. Editing the file sidesteps the whole problem.
        try:
            if not SETTINGS_PATH.exists():
                save_settings(self.servers, self.active)
            os.startfile(str(SETTINGS_PATH))  # noqa: S606 -- user's own settings file
            icon.notify("Edit the file, then choose Reload servers.", "KubunDictate")
        except Exception:
            log("opening the settings file failed", exc=True)

    def _on_reload(self, icon, item):
        try:
            self.servers, self.active = load_settings()
            self._apply_active()
            self._refresh_menu()
            active = self._active_entry()
            icon.notify(
                f"Using {active['name']}." if active else "No servers configured.",
                "KubunDictate",
            )
        except Exception:
            log("reloading the settings file failed", exc=True)

    def _on_toggle_startup(self, icon, item):
        set_startup_enabled(not is_startup_enabled())

    def _on_quit(self, icon, item):
        self.stop_event.set()
        icon.stop()

    def _on_ready(self, icon):
        # Windows hides newly-seen tray icons behind the "^" overflow
        # chevron by default -- there's no supported way to force
        # always-visible from the app side, so nudge the user to it once.
        icon.visible = True
        if not self.servers:
            icon.notify(
                "No server set up yet. Right-click the icon -> Edit servers...",
                "KubunDictate",
            )
        elif self._first_run:
            icon.notify("Running in the system tray -- look for it near the clock.", "KubunDictate")

    def run(self):
        # Servers come from the settings file, written by the installer
        # and editable from the menu -- the client never prompts.
        self._first_run = not SETTINGS_PATH.exists()
        self._apply_active()
        self._refresh_menu()

        toast = win_toast.Toast()
        threading.Thread(
            target=lambda: client.run(self.stop_event),
            daemon=True,
        ).start()
        threading.Thread(
            target=_watch_recording,
            args=(self.icon, self._icons, self.stop_event),
            daemon=True,
        ).start()
        threading.Thread(
            target=_watch_toast,
            args=(toast, self.stop_event),
            daemon=True,
        ).start()

        self.icon.run(setup=self._on_ready)


def _enable_dpi_awareness():
    # Without this, Windows treats the process as DPI-unaware and
    # bitmap-stretches every window it creates (tray icon, dialogs, the
    # toast) to match the display's scale factor instead of rendering
    # natively -- soft/blurry edges on anything but 100% scaling. Must
    # run before any window is created, so this is the first thing
    # main() does. Independent WinDLL handles, not ctypes.windll --
    # see win_toast.py's comment on why that accessor is unsafe to
    # mutate shared state on (not the concern for a single one-off call
    # like this, but keeping the habit consistent).
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, Windows 10 1703+.
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore", use_last_error=True).SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def main():
    _enable_dpi_awareness()
    TrayApp().run()


if __name__ == "__main__":
    main()
