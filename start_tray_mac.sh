#!/usr/bin/env bash
# Launches the menu-bar client, detached from the calling terminal.
# Run install_client_mac.sh first if venv/ doesn't exist yet.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$script_dir/venv/bin/python3"

if [ ! -x "$venv_python" ]; then
    echo "venv not found -- run ./install_client_mac.sh first." >&2
    exit 1
fi

nohup "$venv_python" "$script_dir/tray_client_mac.py" >>"$script_dir/kubundictate.log" 2>&1 &
disown
echo "KubunDictate started -- look for its icon in the menu bar."
