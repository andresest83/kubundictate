#!/usr/bin/env bash
# Fully removes the mac client's local state -- venv, settings,
# LaunchAgent, and the Accessibility/Input Monitoring permission grants
# for Terminal -- so the next ./client/mac/install.sh +
# ./client/mac/start_tray.sh is a genuine first-run, including the native
# permission dialogs firing again. Doesn't touch anything tracked in git,
# only local machine state.
#
# Unlike the Windows uninstaller, this deletes the venv unconditionally:
# the server is Windows-only, so a Mac never shares its venv with one.

set -uo pipefail  # no -e: keep going even if a step is already gone/fails

BOLD=$'\033[1m'
YELLOW=$'\033[0;33m'
RESET=$'\033[0m'

# This script sits two levels down (client/mac/); the venv is at the repo
# root.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

echo "=== KubunDictate mac client uninstaller ==="
echo ""

echo "Stopping any running instance..."
pkill -f "tray_client_mac.py" 2>/dev/null || true

echo "Removing venv..."
rm -rf "$repo_root/venv"

echo "Removing settings (~/Library/Application Support/KubunDictate)..."
rm -rf ~/"Library/Application Support/KubunDictate"

echo "Removing LaunchAgent (Run at login), if present..."
launchctl unload -w ~/Library/LaunchAgents/com.kubundictate.trayclient.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.kubundictate.trayclient.plist

echo ""
echo "Resetting Accessibility and Input Monitoring permission for Terminal..."
if tccutil reset Accessibility com.apple.Terminal 2>/dev/null; then
    echo "  Accessibility: reset."
else
    echo "  Accessibility: tccutil reset failed -- remove Terminal manually in"
    echo "  System Settings -> Privacy & Security -> Bedienungshilfen (- button)."
fi
if tccutil reset ListenEvent com.apple.Terminal 2>/dev/null; then
    echo "  Input Monitoring: reset."
else
    echo "  Input Monitoring: tccutil reset failed -- remove Terminal manually in"
    echo "  System Settings -> Privacy & Security -> Eingabeueberwachung (- button)."
fi

echo ""
echo "${BOLD}${YELLOW}Done.${RESET} Fully quit Terminal (Cmd+Q, all windows), reopen it, then:"
echo "  ./client/mac/install.sh"
echo "  ./client/mac/start_tray.sh"
echo "Both permission dialogs should appear fresh on this next launch."
