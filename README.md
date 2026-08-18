# KubunDictate

Local, offline push-to-talk dictation: hold a hotkey, talk, release it,
and the transcription is copied to your clipboard so you can paste
(Ctrl+V) it wherever you want. Runs entirely offline (no cloud API calls)
via [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

It runs as two modes from the same codebase:

- **server** -- runs once, on a machine with an NVIDIA GPU. Loads the
  Whisper model and keeps it resident in VRAM, exposing a transcription
  endpoint over HTTP.
- **client** -- runs on any Windows PC on your LAN (including the server
  box itself), as a system-tray icon. Handles the hotkey, records your
  mic, sends the audio to the server, and copies the returned text to
  your clipboard. No GPU or model download required.

## Status

- **Windows client/server**: working. Server on the GPU box, thin
  clients on any Windows PC on the LAN.
- **Runs unattended at boot**: working, via a Windows Scheduled Task
  (see "Run as a service" below) -- verified surviving a reboot with no
  one logged in.
- **Mac client**: planned, not started.
- **Android client**: planned, not started.

## Setup

### Quick install

After `git clone`, run `install.ps1` from this folder. It asks whether
this machine is a server or a client, then creates the venv and
installs the right dependencies. On the server it also writes
`config.bat`, provisions the Windows Firewall rule, and can register
the startup service. On the client it installs the tray app's
dependencies -- no `config.bat` needed, `start_tray.bat` asks for the
server's address itself the first time it runs. Server setup needs an
elevated (Administrator) PowerShell; client setup does not.

Re-running it is safe -- it skips venv creation if one already exists
and, on the server, asks before overwriting an existing `config.bat`.

### Manual setup

Both modes share one venv and one entrypoint (`kubundictate.py`); which
one runs is controlled by the `KUBUNDICTATE_MODE` environment variable.
This is what `install.ps1` automates -- do it by hand if you'd rather
not run the script, or need to fine-tune something it doesn't ask about.

```
python -m venv venv
venv\Scripts\pip install -r requirements-server.txt   REM on the GPU box
venv\Scripts\pip install -r requirements-client.txt   REM on any other PC
```

Copy `config.bat.example` to `config.bat` and fill in the values for that
machine (see [Configuration](#configuration) below) -- `config.bat` is
gitignored, so each machine keeps its own local settings.

### Server (the GPU box)

```
set KUBUNDICTATE_MODE=server
```

Then run `start.bat`. First run downloads the model (~1.6GB for
`large-v3-turbo`) to the Hugging Face cache. Leave it running -- it's a
resident process serving requests on `KUBUNDICTATE_PORT` (default 50505).

### Client (any Windows PC, including the GPU box itself)

Run `start_tray.bat` (no console window -- just an icon in the system
tray). First run asks for the server's address (LAN IP or Tailscale IP)
and, if the server has one, its shared token. Settings are saved to
`%APPDATA%\KubunDictate\client_settings.json`, which remembers the
last 3 servers you've used -- right-click the tray icon to switch
between them or enter a new one.

- Hold **F9** to record, release to transcribe. The text lands on the
  clipboard automatically -- paste it with Ctrl+V anywhere.
- The tray icon changes color while recording.
- A short beep marks start/stop of recording, a higher beep marks a
  successful transcription, and a low beep marks a failed request (e.g.
  server unreachable).
- Right-click the tray icon -> **Quit** to exit (there's no Esc-to-quit
  here -- Esc is too easy to hit by accident in a background app).
- Right-click -> **Run at startup** to toggle launching automatically at
  login (adds/removes a `pythonw.exe start_tray.bat`-equivalent entry
  under the current user's Registry Run key). Off by default -- launch
  `start_tray.bat` manually otherwise.

For a plain console client instead (no tray icon, `config.bat`-driven):

```
set KUBUNDICTATE_MODE=client
set KUBUNDICTATE_SERVER_URL=http://<server-ip>:50505
```

Then run `start.bat`. Same hotkey/beep behavior as above, plus
**Esc** (while not recording) to quit, since there's a console attached.

To dictate directly on the GPU box, just install the tray client there
too and point it at `localhost` -- `install.ps1`'s server path offers
to set this up right after server setup (installs the tray
dependencies into the same venv and pre-fills
`start_tray.bat`'s settings, so it needs zero setup on first launch).

## Run silently / at startup

`start_hidden.bat` runs the same thing with no visible console window,
logging output to `kubundictate.log` instead. `start_silent.vbs` launches
that batch file with zero windows at all (double-clicking it shows nothing,
which is the point).

To run it automatically at login: press `Win+R`, type `shell:startup`,
and drop a shortcut to `start_silent.vbs` in that folder. Not done for you
automatically -- add it yourself if you want that behavior.

## Run as a service (Windows startup, no login required)

For the GPU box, `start_silent.vbs` at login only helps once someone's
logged in. To have the server come up at boot -- before any login, and
stay up across logout -- register it as a scheduled task instead:

```
install_service.ps1
```

Run from an **elevated** (Administrator) PowerShell. It registers a
Scheduled Task named `KubunDictateServer` that runs `start_hidden.bat`
at startup as `NT AUTHORITY\SYSTEM`, with automatic restart on failure.
Requires `config.bat` in this folder to already have
`KUBUNDICTATE_MODE=server` set.

- Start it immediately without rebooting: `Start-ScheduledTask -TaskName KubunDictateServer`
- Logs: same `kubundictate.log` as `start_hidden.bat`
- Remove it: `uninstall_service.ps1` (also elevated)

This uses Task Scheduler rather than a "real" Windows service (no new
dependencies, reuses the existing hidden launcher) -- close enough for a
single-user home GPU box. A `pywin32`-based service remains an option
later if `services.msc` integration is ever actually needed.

### Check status

```
status.ps1
```

No elevation needed -- run it from any PowerShell prompt on the server
box. Reports whether the scheduled task is running and whether the
server is actually answering requests (`/health`), in one summary
instead of two separate things to remember.

## Configuration

The tray client (`start_tray.bat`) doesn't use `config.bat` at all --
its server address/token are set through its own first-run prompt and
tray menu, stored in `%APPDATA%\KubunDictate\client_settings.json`.
These apply to the server and to the plain console client
(`set X=Y` before `start.bat`, or in `config.bat`):

- `KUBUNDICTATE_MODE` -- `server` or `client`. Required, no default.
- `KUBUNDICTATE_SERVER_URL` -- (console client only) the server's
  address, e.g. `http://192.168.1.50:50505` on the LAN, or a
  [Tailscale](https://tailscale.com/) IP/hostname for off-LAN use.
  Required for console client mode.
- `KUBUNDICTATE_HOST` -- (server only) bind address. Default `0.0.0.0`.
- `KUBUNDICTATE_PORT` -- (server only) port. Default `50505`.
- `KUBUNDICTATE_MODEL` -- (server only) faster-whisper model size/name.
  Default `large-v3-turbo`. Smaller/faster options: `distil-large-v3`,
  `medium`, `small`. See
  [available models](https://github.com/SYSTRAN/faster-whisper#model-conversion).
- `KUBUNDICTATE_LANGUAGE` -- (server only) force a language code (e.g.
  `en`) to skip auto-detection and speed things up slightly. Default:
  auto-detect.
- `KUBUNDICTATE_TOKEN` -- (server + console client) shared secret. If
  set on the server, clients must send the same value or requests are
  rejected. Optional, **off by default** -- `install.ps1` prompts on
  server setups: Enter for none, `generate` for a strong random one, or
  type your own (8+ chars, needs a letter, a number, and one of
  `-_.~+`). That character set is deliberately narrow: `config.bat` is
  `call`ed by `cmd.exe`, which treats `%` and `^` (among others) as
  special and silently corrupts them, desyncing the server's real token
  from what clients were told -- happened once, not fun to debug, so
  the generator and the strength check both stick to characters that
  are inert in a batch file. If you do set one, it's printed prominently
  (and saved to `server-token.txt`, gitignored) so you can enter it into
  each client's tray icon (right-click -> Enter new server...). Worth
  setting if you're not sure who else is on your LAN; a trusted home
  network or Tailscale-only setup is a reasonable case to leave it off.

To change the hotkey, edit `HOTKEY` in `client.py` (uses
[pynput](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.Key) key names).

## Remote access

Reachable on your LAN by default. For access from outside your LAN, use
[Tailscale](https://tailscale.com/) on both the server and client machines
and point `KUBUNDICTATE_SERVER_URL` at the server's Tailscale IP -- no
other WAN exposure is supported or recommended.

## Why not whisper-writer?

The initial plan was to wrap [whisper-writer](https://github.com/savbell/whisper-writer),
an existing open-source app that already does hotkey-record-transcribe and
also auto-types the result into the focused window. Once it was clear the
actual requirement was simpler -- just put the text on the clipboard and
paste it manually, not auto-type into arbitrary apps -- whisper-writer's
extra machinery (window-focus tracking, simulated keystroke injection,
its own config/UI layer) stopped earning its keep. This project is built
directly on faster-whisper + sounddevice + pynput + pyperclip + FastAPI
instead: fewer dependencies, easier to read and modify, and no behavior
beyond what's actually needed.

## Hardware notes (server)

Tuned for an RTX 5060 Ti (Blackwell, 16GB VRAM). Two Blackwell-specific
things matter here:

1. `compute_type` is hardcoded to `float16` in `server.py`. CTranslate2's
   default/int8 path crashes on RTX 50-series GPUs with
   `CUBLAS_STATUS_NOT_SUPPORTED` -- float16 is the known-good workaround.
2. `server.py` adds the `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` pip
   packages' DLL directories to `PATH` at import time, since CTranslate2
   needs cuBLAS/cuDNN on Windows and doesn't bundle them itself.

`large-v3-turbo` comfortably fits in 16GB VRAM with room to spare (~2-3GB
used at rest). If you ever run the server alongside something else that's
VRAM-hungry, drop to `distil-large-v3` or `medium` via `KUBUNDICTATE_MODEL`.

## Files

- `kubundictate.py` -- entrypoint, dispatches to `server.py` or `client.py`
  based on `KUBUNDICTATE_MODE`
- `server.py` -- FastAPI transcription server (GPU box)
- `client.py` -- hotkey/record/clipboard engine, shared by the console
  client and the tray client
- `tray_client.py` -- system-tray client: same engine as `client.py`,
  plus the tray icon/menu and the recent-servers settings file (see
  "Client")
- `audio.py` -- shared WAV<->float32 conversion helpers
- `venv/` -- self-contained Python virtual environment (not committed)
- `install.ps1` -- one-shot setup: venv, dependencies, `config.bat`
  (server only), firewall rule, and (optionally) the startup service
  (see "Quick install")
- `start.bat` / `start_hidden.bat` / `start_silent.vbs` -- launchers
- `start_tray.bat` -- launches the tray client (`pythonw.exe`, no
  console window)
- `install_service.ps1` / `uninstall_service.ps1` -- register/remove the
  server as a Scheduled Task that runs at boot (see "Run as a service")
- `status.ps1` -- one-command server status check: scheduled task state
  + a live `/health` hit (see "Check status")
- `config.bat.example` -- template for per-machine settings (copy to
  `config.bat`, which is gitignored)
- `requirements-server.txt` / `requirements-client.txt` -- pip
  dependencies for each mode
