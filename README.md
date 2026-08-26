# KubunDictate

![KubunDictate architecture](images/kubundictate-architecture.png)

**TL;DR:** Hold a key, talk, let go, and your words land on your
clipboard, ready to paste anywhere. It runs entirely on your own hardware: no
cloud, no accounts, nothing leaves your network. One computer with a
graphics card does the actual transcribing; any other Windows PC or
Mac on the same network can use it. Windows and Mac are both done and
working today.

## What you need

- **One PC with an NVIDIA graphics card.** This is the "server": it
  does the transcribing. Set it up once.
- **Any number of other computers** (Windows or Mac) to actually talk
  into day to day: these are "clients." No graphics card needed. You
  can also use the server PC itself as a client.

## Set up the server (the PC with the graphics card)

Open PowerShell as Administrator, then from this folder:

```
install_server.ps1
```

It asks a few quick questions (port, which speech model, an optional
shared password) and sets everything up. Then start it:

```
start_server.bat
```

The first run downloads the speech model (a few GB). That only
happens once. Leave this running; it's what your clients talk to.

Want it to start on its own every time this PC turns on? See
[Start the server automatically](#start-the-server-automatically) below.

## Set up a client (any other computer)

**Windows:**

```
install_client.ps1
start_tray.bat
```

**Mac:**

```
./install_client_mac.sh
./start_tray_mac.sh
```

The first time it runs, it asks for the server's address: just the
IP address of the server PC on your network (or `localhost` if this
is the same computer as the server).

On a Mac, the first launch also asks for two permissions
(**Accessibility** and **Input Monitoring**, under System Settings →
Privacy & Security). Click Allow for both, then quit and reopen the
app once, since permissions only take effect after a restart. If your Mac
is set to German, these are labeled *Bedienungshilfen* and
*Eingabeüberwachung*.

## Using it

- Hold **F9** (Windows) or **Left Option** (Mac) to record, let go to
  transcribe. Left Option is used on Mac because F-keys default to
  media controls there.
- The text lands on your clipboard automatically. Paste it anywhere
  with Ctrl+V (Cmd+V on Mac).
- A small popup near the top of your screen and a short sound confirm
  what's happening: listening, working, done.
- Right-click the tray icon (Windows) or click the menu-bar icon (Mac)
  for more: switch between recent servers, enter a new one, or turn on
  "run automatically at startup."

## Start the server automatically

To have the server come up on its own at boot, even before anyone logs
in, from an **Administrator** PowerShell:

```
install_server_service.ps1
```

Check whether it's running any time with:

```
status_server.ps1
```

Turn it off again with `uninstall_server_service.ps1`.

## Starting fresh

If something's acting up and you want a clean slate for a client:

```
uninstall_client.ps1     REM Windows
./uninstall_client_mac.sh   # Mac
```

This removes everything the installer set up (but never anything the
server needs, even if you run both roles on the same machine). Run
the install command again afterward for a genuine fresh start.

## Using it away from home

Works on your home network automatically. To reach it from elsewhere
(say, a laptop out and about), install [Tailscale](https://tailscale.com/)
on both the server and client, and point the client at the server's
Tailscale address instead. Nothing else needs to be opened up to the
internet.

## Settings

- **Server:** edit `config.bat` in the server's folder: port, which
  speech model to use, and an optional shared password if you want to
  restrict who can use it (off by default; fine to leave off on a
  trusted home network).
- **Client:** everything's in the tray/menu-bar icon. No file to
  edit.

## Why not just use an existing tool?

The starting point was [whisper-writer](https://github.com/savbell/whisper-writer),
which already does hotkey-record-transcribe and also auto-types the
result into whatever app is focused. Once it was clear that "put it on
the clipboard, paste it yourself" was actually enough, whisper-writer's
extra machinery for auto-typing stopped earning its keep, so this
project is a smaller, purpose-built alternative instead.

## A note on the server's graphics card

The default speech model comfortably fits on a 16GB graphics card with
room to spare. If you're also running something else that uses a lot
of graphics memory, switch to a smaller/faster model via
`KUBUNDICTATE_MODEL` in `config.bat` (`distil-large-v3` or `medium`
use noticeably less).

## Project files

| File | What it's for |
|---|---|
| `server.py` | The server program |
| `client.py` | Shared recording/transcribing logic used by both clients |
| `tray_client.py` | Windows tray client |
| `tray_client_mac.py` | Mac menu-bar client |
| `install_server.ps1` / `install_client.ps1` | One-time Windows setup for each role |
| `uninstall_client.ps1` | Removes a Windows client's local setup |
| `install_client_mac.sh` / `uninstall_client_mac.sh` | Same, for Mac |
| `start_server.bat` / `start_tray.bat` / `start_tray_mac.sh` | Everyday launchers |
| `install_server_service.ps1` / `uninstall_server_service.ps1` | Start the server automatically at boot |
| `status_server.ps1` | One-command check: is the server up? |
| `config.bat.example` | Template for the server's settings |
| `requirements-*.txt` | The pip packages each role needs |
