"""Menu-bar client: same record/transcribe engine as client.py, but as a
rumps menu-bar app instead of a console window, with a small "recent
servers" list instead of hand-editing env vars.

macOS equivalent of tray_client.py (which is Windows-only: pystray,
winreg, tkinter). Settings (recent servers + their tokens) live in
~/Library/Application Support/KubunDictate/client_settings.json -- the
mac analogue of tray_client.py's %APPDATA% location. Run via
start_tray_mac.sh.

First launch prompts macOS for Input Monitoring (needed for the global
hotkey listener) and Microphone access -- native OS prompts, no in-app
handling here; see README.md.
"""

import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import rumps
from PIL import Image, ImageDraw

import client

MAX_RECENT = 3
IDLE_COLOR = (46, 134, 222, 255)
RECORD_COLOR = (235, 77, 75, 255)

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


def _make_icon_file(color):
    # rumps.App.icon wants a file path, not an in-memory image like
    # pystray accepts -- render once per color and swap paths instead.
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 6
    draw.ellipse((margin, margin, size - margin, size - margin), fill=color)
    fd, path = tempfile.mkstemp(suffix=".png", prefix="kubundictate_icon_")
    os.close(fd)
    img.save(path)
    return path


class TrayApp(rumps.App):
    def __init__(self):
        self.recent = load_recent()
        self.stop_event = threading.Event()
        self._recording = False
        self._idle_icon = _make_icon_file(IDLE_COLOR)
        self._record_icon = _make_icon_file(RECORD_COLOR)
        # quit_button=None so our own Quit item can set stop_event before
        # calling rumps.quit_application().
        super().__init__("KubunDictate", icon=self._idle_icon, quit_button=None)
        self._rebuild_menu()

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
        current = client.is_recording()
        if current != self._recording:
            self._recording = current
            self.icon = self._record_icon if current else self._idle_icon

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
    TrayApp().run()


if __name__ == "__main__":
    main()
