#!/usr/bin/env bash
# Launches the menu-bar client, detached from the calling terminal.
# Run client/mac/install.sh first if venv/ doesn't exist yet.
#
# This script sits two levels down (client/mac/): tray_client_mac.py is
# one level up in client/, and the venv is at the repo root.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
client_dir="$(cd "$script_dir/.." && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
venv_python="$repo_root/venv/bin/python3"

if [ ! -x "$venv_python" ]; then
    echo "venv not found -- run ./client/mac/install.sh first." >&2
    exit 1
fi

nohup "$venv_python" "$client_dir/tray_client_mac.py" >>"$client_dir/kubundictate.log" 2>&1 &
disown
echo "KubunDictate started -- look for its icon in the menu bar."
