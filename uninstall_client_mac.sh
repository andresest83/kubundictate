#!/usr/bin/env bash
# Fully removes the mac client's local state -- venv, settings,
# LaunchAgent, and the Accessibility/Input Monitoring permission grants
# for Terminal -- so the next ./install_client_mac.sh + ./start_tray_mac.sh
# is a genuine first-run, including the native permission dialogs firing
# again. Doesn't touch anything tracked in git, only local machine state.

set -uo pipefail  # no -e: keep going even if a step is already gone/fails

BOLD=$'\033[1m'
YELLOW=$'\033[0;33m'
RESET=$'\033[0m'

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== KubunDictate mac client uninstaller ==="
echo ""

echo "Stopping any running instance..."
pkill -f "tray_client_mac.py" 2>/dev/null || true

echo "Removing venv..."
rm -rf "$script_dir/venv"

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
echo "  ./install_client_mac.sh"
echo "  ./start_tray_mac.sh"
echo "Both permission dialogs should appear fresh on this next launch."
