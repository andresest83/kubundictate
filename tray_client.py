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
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog

from PIL import Image, ImageDraw
import pystray

import client

MAX_RECENT = 3
IDLE_COLOR = (46, 134, 222, 255)
RECORD_COLOR = (235, 77, 75, 255)

SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "KubunDictate"
SETTINGS_PATH = SETTINGS_DIR / "client_settings.json"


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


def _make_icon_image(color):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 6
    draw.ellipse((margin, margin, size - margin, size - margin), fill=color)
    return img


def _watch_recording(icon, stop_event):
    last = False
    while not stop_event.is_set():
        current = client.is_recording()
        if current != last:
            icon.icon = _make_icon_image(RECORD_COLOR if current else IDLE_COLOR)
            last = current
        time.sleep(0.15)


class TrayApp:
    def __init__(self):
        self.recent = load_recent()
        self.stop_event = threading.Event()
        self._tk_root = None
        self.icon = pystray.Icon(
            "kubundictate",
            icon=_make_icon_image(IDLE_COLOR),
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

    def _on_quit(self, icon, item):
        self.stop_event.set()
        icon.stop()

    def _on_ready(self, icon):
        # Windows hides newly-seen tray icons behind the "^" overflow
        # chevron by default -- there's no supported way to force
        # always-visible from the app side, so nudge the user to it once.
        icon.visible = True
        if self._first_run:
            icon.notify(
                "Look for the KubunDictate icon near the clock -- click the "
                "^ arrow to find hidden icons, then drag it out to always show.",
                "KubunDictate is running",
            )

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
            target=lambda: client.run(self.stop_event, quit_on_esc=False),
            daemon=True,
        ).start()
        threading.Thread(
            target=_watch_recording, args=(self.icon, self.stop_event), daemon=True
        ).start()

        self.icon.run(setup=self._on_ready)


def main():
    TrayApp().run()


if __name__ == "__main__":
    main()
