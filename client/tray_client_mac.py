"""Menu-bar client: same record/transcribe engine as client.py, but as a
rumps menu-bar app instead of a console window, with a named list of
servers to switch between (typically a LAN address and a Tailscale one).

macOS equivalent of tray_client.py (which is Windows-only: pystray,
winreg). Servers live in
~/Library/Application Support/KubunDictate/client_settings.json -- the
mac analogue of tray_client.py's %APPDATA% location, in the same format,
written by mac/install.sh and editable from the menu. Neither client
prompts for an address; see tray_client.py for why that dialog was
dropped. Run via mac/start_tray.sh.

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
import traceback
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

ICON_DIR = Path(__file__).resolve().parent / "icons"
ICON_SOURCE_SIZE = 48  # nearest pre-rendered size at/above ICON_RENDER_SIZE
ICON_RENDER_SIZE = 44  # @2x for a 22pt menu-bar icon
PULSE_INTERVAL = 0.7  # seconds between listening-a/listening-b swaps

SETTINGS_DIR = Path.home() / "Library" / "Application Support" / "KubunDictate"
SETTINGS_PATH = SETTINGS_DIR / "client_settings.json"
LOG_PATH = SETTINGS_DIR / "client.log"

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


def log(message, exc=False):
    """Append a line to the client log, optionally with a traceback.

    Mirrors the Windows client. Errors inside a menu callback are easy to
    lose -- rumps runs them on the AppKit run loop -- so there is always
    somewhere to look.
    """
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
            if exc:
                traceback.print_exc(file=fh)
    except OSError:
        pass


def load_settings():
    """Reads the settings file, returning (servers, active_name).

    Identical contract to the Windows client's, so one settings file
    format serves both. Written to tolerate hand editing, since that is
    now how servers get added: entries without a name get one, bare
    addresses are expanded to full URLs, blank entries are dropped, and
    the older {"recent": [...]} shape is migrated.
    """
    # utf-8-sig rather than utf-8: an editor may leave a byte-order mark,
    # and a plain utf-8 read rejects one outright. Harmless when absent.
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return [], None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        # An unreadable file otherwise looks exactly like "no servers
        # configured", which is maddening to debug from the menu alone.
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


def display_url(url):
    """Strips the scheme off for display in the menu."""
    prefix = "http://"
    return url[len(prefix):] if url.startswith(prefix) else url


def normalize_url(addr):
    addr = addr.strip()
    if addr.startswith("http://") or addr.startswith("https://"):
        return addr
    if not re.search(r":\d+$", addr):
        addr = f"{addr}:9505"
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
    # Pre-rendered per state/size in icons/ (see
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
        self.servers, self.active = load_settings()
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

    def _rebuild_menu(self):
        items = []
        active = self._active_entry()
        if active:
            items.append(rumps.MenuItem(f"Using: {active['name']}"))
        else:
            items.append(rumps.MenuItem("No server set up -- see Edit servers..."))
        items.append(rumps.separator)

        for entry in self.servers:
            item = rumps.MenuItem(
                f"{entry['name']}  ({display_url(entry['url'])})",
                callback=self._make_select_handler(entry),
            )
            item.state = entry["name"] == self.active
            items.append(item)
        if self.servers:
            items.append(rumps.separator)

        items.append(rumps.MenuItem("Edit servers...", callback=self._on_edit_servers))
        items.append(rumps.MenuItem("Reload servers", callback=self._on_reload))
        items.append(rumps.separator)

        startup_item = rumps.MenuItem("Run at login", callback=self._on_toggle_startup)
        startup_item.state = is_startup_enabled()
        items.append(startup_item)

        items.append(rumps.MenuItem("Quit", callback=self._on_quit))
        self.menu = items

    def _make_select_handler(self, entry):
        def handler(sender):
            try:
                self.active = entry["name"]
                save_settings(self.servers, self.active)
                self._apply_active()
                self._rebuild_menu()
            except Exception:
                log(f"switching to server {entry['name']!r} failed", exc=True)

        return handler

    def _on_edit_servers(self, sender):
        # Opens the file in whatever handles .json (TextEdit by default)
        # instead of prompting. Matches the Windows client, which had to
        # drop its own dialog entirely -- see tray_client.py -- so both
        # platforms manage servers exactly the same way.
        try:
            if not SETTINGS_PATH.exists():
                save_settings(self.servers, self.active)
            subprocess.run(["open", str(SETTINGS_PATH)], check=False)
            rumps.notification(
                "KubunDictate", "", "Edit the file, then choose Reload servers."
            )
        except Exception:
            log("opening the settings file failed", exc=True)

    def _on_reload(self, sender):
        try:
            self.servers, self.active = load_settings()
            self._apply_active()
            self._rebuild_menu()
            active = self._active_entry()
            rumps.notification(
                "KubunDictate",
                "",
                f"Using {active['name']}." if active else "No servers configured.",
            )
        except Exception:
            log("reloading the settings file failed", exc=True)

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
        # Servers come from the settings file, written by the installer
        # and editable from the menu -- the client never prompts.
        self._apply_active()
        if not self.servers:
            rumps.notification(
                "KubunDictate", "", "No server set up yet. Menu bar icon -> Edit servers..."
            )

        threading.Thread(target=lambda: client.run(self.stop_event), daemon=True).start()
        rumps.Timer(self._check_recording, 0.15).start()

        super().run()


def main():
    _request_accessibility_trust()
    _request_input_monitoring_access()
    # Route the engine's diagnostics into the same file, as on Windows.
    client.log = log
    TrayApp().run()


if __name__ == "__main__":
    main()
