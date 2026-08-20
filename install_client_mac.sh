#!/usr/bin/env bash
# One-shot client setup: creates the venv and installs the menu-bar
# client's dependencies. Run from this folder after `git clone`, on the
# Mac that will run tray_client_mac.py. No elevation needed.
#
# For the server (the GPU box), see install_server.ps1 -- server setup
# is Windows-only.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="$script_dir/venv"
venv_python="$venv_dir/bin/python3"

echo "=== KubunDictate mac client installer ==="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found on PATH. Install Python 3.10+ yourself (this script doesn't install it for you), then re-run." >&2
    exit 1
fi

if [ -x "$venv_python" ]; then
    echo "venv already exists at $venv_dir -- skipping creation."
else
    echo "Creating venv..."
    python3 -m venv "$venv_dir"
fi

requirements_file="$script_dir/requirements-client-mac.txt"
echo "Installing dependencies from $(basename "$requirements_file")..."
"$venv_python" -m pip install --upgrade pip --quiet
"$venv_python" -m pip install -r "$requirements_file"

echo ""
echo "=== Done ==="
echo "Run ./start_tray_mac.sh to start dictating -- it asks for your server's LAN or"
echo "Tailscale address (localhost:<port> if this is the server's own box, and its"
echo "token, if it has one) the first time it runs, and remembers the last 3 you've used."
echo ""
echo "Hold Left Option to talk (not F9 -- bare F-keys default to media functions"
echo "on a Mac keyboard). First launch needs two separate permissions, both under"
echo "System Settings -> Privacy & Security: Accessibility and Input Monitoring"
echo "(Eingabeueberwachung in German). The app triggers both native prompts on"
echo "first launch -- click Allow/Open System Settings on each, then quit and"
echo "relaunch. If a permission dialog doesn't list your Terminal app yet, add"
echo "it via + (add Terminal itself, not python3 -- the file picker won't even"
echo "let you select a raw binary). See README.md's 'Client (macOS)' section for"
echo "the full troubleshooting path if the hotkey still does nothing afterward."
