#!/usr/bin/env bash
# Launches the menu-bar client attached to this terminal (not detached),
# on purpose, while the mac client is still being verified end-to-end --
# keeps prints/errors visible right here instead of only in
# kubundictate.log, so there's one launch path instead of "run this
# normally, but run the raw python directly whenever something needs
# debugging." Switch back to a detached background launch (nohup + &)
# once the mac client is confirmed solid.
#
# Run install_client_mac.sh first if venv/ doesn't exist yet.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$script_dir/venv/bin/python3"

if [ ! -x "$venv_python" ]; then
    echo "venv not found -- run ./install_client_mac.sh first." >&2
    exit 1
fi

exec "$venv_python" "$script_dir/tray_client_mac.py"
