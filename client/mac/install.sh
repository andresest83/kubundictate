#!/usr/bin/env bash
# One-shot client setup: creates the venv and installs the menu-bar
# client's dependencies. Run as `client/mac/install.sh` from the repo
# root after `git clone`, on the Mac that will run tray_client_mac.py.
# No elevation needed.
#
# For the server (the GPU box), see server/install.ps1 -- server setup
# is Windows-only.

set -euo pipefail

BOLD=$'\033[1m'
YELLOW=$'\033[0;33m'
RESET=$'\033[0m'

# This script sits two levels down (client/mac/). The venv lives at the
# repo root, matching where the Windows side puts it.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
venv_dir="$repo_root/venv"
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

requirements_file="$script_dir/requirements.txt"
echo "Installing dependencies from $(basename "$requirements_file")..."
"$venv_python" -m pip install --upgrade pip --quiet
"$venv_python" -m pip install -r "$requirements_file"

# --- server list ---
# Collected here rather than in the app: the Windows client had to drop
# its own text-entry dialog entirely (it could never take keyboard focus
# from the tray menu), so both platforms now read the same settings file
# and the menu only switches between named entries.
settings_dir="$HOME/Library/Application Support/KubunDictate"
settings_path="$settings_dir/client_settings.json"

write_settings=yes
if [ -f "$settings_path" ]; then
    printf 'Server list already exists. Replace it? [y/N] '
    read -r replace
    case "$replace" in
        [Yy]*) write_settings=yes ;;
        *)     write_settings=no ;;
    esac
fi

if [ "$write_settings" = yes ]; then
    echo ""
    echo "Where is the server? This is the Windows PC with the graphics card."
    printf 'Server address (e.g. 192.168.1.50:9505): '
    read -r lan
    lan="${lan:-192.168.1.50:9505}"

    echo ""
    echo "Optional: a Tailscale address for using this away from home."
    printf 'Tailscale address (blank to skip): '
    read -r tailscale

    echo ""
    echo "Only needed if the server was set up with a shared token."
    printf 'Shared token (blank = none): '
    read -r token

    if [ -n "$token" ]; then
        token_json="\"$token\""
    else
        token_json="null"
    fi

    mkdir -p "$settings_dir"
    {
        printf '{\n  "servers": [\n'
        printf '    { "name": "Local", "url": "%s", "token": %s }' "$lan" "$token_json"
        if [ -n "$tailscale" ]; then
            printf ',\n    { "name": "Tailscale", "url": "%s", "token": %s }' \
                "$tailscale" "$token_json"
        fi
        printf '\n  ],\n  "active": "Local"\n}\n'
    } > "$settings_path"
    echo ""
    echo "Wrote $settings_path"
else
    echo "Keeping the existing server list."
fi

echo ""
echo "=== Done ==="
echo "Run ./client/mac/start_tray.sh to start dictating."
echo "Switch servers, or edit the list, from the menu-bar icon."
echo ""
echo "${BOLD}${YELLOW}Hold Left Option${RESET} to record, release to transcribe."
echo ""
echo "${BOLD}First launch needs two permissions${RESET} (System Settings -> Privacy & Security):"
echo "  - ${YELLOW}Accessibility${RESET}"
echo "  - ${YELLOW}Input Monitoring${RESET} (${YELLOW}Eingabeueberwachung${RESET} in German)"
echo ""
echo "A native dialog pops up for each on first launch -- click ${BOLD}Allow${RESET} or"
echo "${BOLD}Open System Settings${RESET}, then ${BOLD}quit and relaunch${RESET}."
echo ""
echo "If Terminal isn't listed under either permission yet: click ${BOLD}+${RESET} and add"
echo "${BOLD}Terminal itself${RESET} (not python3 -- the picker won't let you select a raw binary)."
echo ""
echo "Still stuck? See README.md -> 'Set up a client' for the full troubleshooting steps."
