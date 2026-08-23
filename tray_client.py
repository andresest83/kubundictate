"""System-tray client: same record/transcribe engine as client.py, but as
a tray icon instead of a console window, with a small "recent servers"
list instead of hand-editing config.bat.

Settings (recent servers + their tokens) live in
%APPDATA%\\KubunDictate\\client_settings.json -- separate from the
server's config.bat, since this is meant to be run standalone (no repo
folder needed once it's set up). Run via start_tray.bat (pythonw.exe,
no console window).
"""

import json
import os
import re
import sys
import threading
import time
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import simpledialog

from PIL import Image
import pystray

import client

MAX_RECENT = 3
ICON_DIR = Path(__file__).resolve().parent / "images"
ICON_SIZE = 64  # matches images/kubundictate-<state>-64.png
PULSE_INTERVAL = 0.7  # seconds between listening-a/listening-b swaps

SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "KubunDictate"
SETTINGS_PATH = SETTINGS_DIR / "client_settings.json"

STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "KubunDictate"


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
    # state/size in images/ (see kubundictate-icons/README.md).
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
        self.recent = load_recent()
        self.stop_event = threading.Event()
        self._tk_root = None
        self._icons = _load_icons()
        self.icon = pystray.Icon(
            "kubundictate",
            icon=self._icons["idle"],
            title="KubunDictate",
            menu=self._build_menu(),
        )

    def _get_tk_root(self):
        if self._tk_root is None:
            self._tk_root = tk.Tk()
            self._tk_root.withdraw()
        return self._tk_root

    def _prompt_for_server(self, initial_token=""):
        root = self._get_tk_root()
        root.attributes("-topmost", True)
        addr = simpledialog.askstring(
            "KubunDictate",
            "Server address, e.g. 192.168.1.50:50505 or a Tailscale IP:",
            parent=root,
        )
        if not addr or not addr.strip():
            return None
        url = normalize_url(addr)
        token = simpledialog.askstring(
            "KubunDictate",
            "Shared token (blank = none):",
            parent=root,
            initialvalue=initial_token or "",
        )
        return {"url": url, "token": (token or None)}

    def _apply_active(self):
        if self.recent:
            active = self.recent[0]
            client.settings.server_url = active["url"]
            client.settings.token = active["token"]

    def _refresh_menu(self):
        self.icon.menu = self._build_menu()

    def _build_menu(self):
        items = []
        if self.recent:
            items.append(pystray.MenuItem(f"Server: {self.recent[0]['url']}", None, enabled=False))
        else:
            items.append(pystray.MenuItem("No server configured", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)

        for entry in self.recent:
            items.append(
                pystray.MenuItem(
                    entry["url"],
                    self._make_select_handler(entry),
                    checked=self._make_checked(entry),
                    radio=True,
                )
            )

        items.append(pystray.MenuItem("Enter new server...", self._on_new_server))
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
            self.recent = add_or_promote(self.recent, entry["url"], entry["token"])
            save_recent(self.recent)
            self._apply_active()
            self._refresh_menu()

        return handler

    def _make_checked(self, entry):
        def checked(item):
            return bool(self.recent) and self.recent[0]["url"] == entry["url"]

        return checked

    def _on_new_server(self, icon, item):
        current_token = self.recent[0]["token"] if self.recent else ""
        result = self._prompt_for_server(initial_token=current_token)
        if not result:
            return
        self.recent = add_or_promote(self.recent, result["url"], result["token"])
        save_recent(self.recent)
        self._apply_active()
        self._refresh_menu()

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
        if self._first_run:
            icon.notify("Running in the system tray -- look for it near the clock.", "KubunDictate")

    def run(self):
        self._first_run = not self.recent
        if self._first_run:
            result = self._prompt_for_server()
            if not result:
                return
            self.recent = add_or_promote(self.recent, result["url"], result["token"])
            save_recent(self.recent)
        self._apply_active()
        self._refresh_menu()

        threading.Thread(
            target=lambda: client.run(self.stop_event),
            daemon=True,
        ).start()
        threading.Thread(
            target=_watch_recording,
            args=(self.icon, self._icons, self.stop_event),
            daemon=True,
        ).start()

        self.icon.run(setup=self._on_ready)


def main():
    TrayApp().run()


if __name__ == "__main__":
    main()
