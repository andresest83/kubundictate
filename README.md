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
  box itself). Handles the hotkey, records your mic, sends the audio to
  the server, and copies the returned text to your clipboard. No GPU or
  model download required.

## Status

- **Windows client/server**: working. Server on the GPU box, thin
  clients on any Windows PC on the LAN.
- **Runs unattended at boot**: working, via a Windows Scheduled Task
  (see "Run as a service" below) -- verified surviving a reboot with no
  one logged in.
- **Mac client**: planned, not started.
- **Android client**: planned, not started.

## Setup

Both modes share one venv and one entrypoint (`kubundictate.py`); which
one runs is controlled by the `KUBUNDICTATE_MODE` environment variable.

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

```
set KUBUNDICTATE_MODE=client
set KUBUNDICTATE_SERVER_URL=http://<server-ip>:50505
```

Then run `start.bat`.

- Hold **F9** to record, release to transcribe. The text lands on the
  clipboard automatically -- paste it with Ctrl+V anywhere.
- Press **Esc** (while not recording) to quit.
- A short beep marks start/stop of recording, a higher beep marks a
  successful transcription, and a low beep marks a failed request (e.g.
  server unreachable) -- so you don't need to watch the console.

If you want hotkey dictation directly on the GPU box too, run a second
`client` process there pointed at `http://localhost:50505` alongside the
`server` process.

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
- Check status: `Get-ScheduledTask -TaskName KubunDictateServer`
- Logs: same `kubundictate.log` as `start_hidden.bat`
- Remove it: `uninstall_service.ps1` (also elevated)

This uses Task Scheduler rather than a "real" Windows service (no new
dependencies, reuses the existing hidden launcher) -- close enough for a
single-user home GPU box. A `pywin32`-based service remains an option
later if `services.msc` integration is ever actually needed.

## Configuration

Set these in `config.bat` (or the environment before running):

- `KUBUNDICTATE_MODE` -- `server` or `client`. Required, no default.
- `KUBUNDICTATE_SERVER_URL` -- (client only) the server's address, e.g.
  `http://192.168.1.50:50505` on the LAN, or a
  [Tailscale](https://tailscale.com/) IP/hostname for off-LAN use.
  Required for client mode.
- `KUBUNDICTATE_HOST` -- (server only) bind address. Default `0.0.0.0`.
- `KUBUNDICTATE_PORT` -- (server only) port. Default `50505`.
- `KUBUNDICTATE_MODEL` -- (server only) faster-whisper model size/name.
  Default `large-v3-turbo`. Smaller/faster options: `distil-large-v3`,
  `medium`, `small`. See
  [available models](https://github.com/SYSTRAN/faster-whisper#model-conversion).
- `KUBUNDICTATE_LANGUAGE` -- (server only) force a language code (e.g.
  `en`) to skip auto-detection and speed things up slightly. Default:
  auto-detect.
- `KUBUNDICTATE_TOKEN` -- optional shared secret. If set on the server,
  clients must send the same value or requests are rejected. Off by
  default -- fine for a trusted LAN/Tailscale network, but recommended if
  you're at all unsure who else is on it.

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
- `client.py` -- hotkey/record/clipboard client
- `audio.py` -- shared WAV<->float32 conversion helpers
- `venv/` -- self-contained Python virtual environment (not committed)
- `start.bat` / `start_hidden.bat` / `start_silent.vbs` -- launchers
- `install_service.ps1` / `uninstall_service.ps1` -- register/remove the
  server as a Scheduled Task that runs at boot (see "Run as a service")
- `config.bat.example` -- template for per-machine settings (copy to
  `config.bat`, which is gitignored)
- `requirements-server.txt` / `requirements-client.txt` -- pip
  dependencies for each mode
