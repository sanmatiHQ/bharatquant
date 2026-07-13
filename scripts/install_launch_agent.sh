#!/usr/bin/env bash
# Install macOS LaunchAgent — supervisor restarts on login and stays alive 24×7
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/deploy/com.bharatquant.supervisor.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.bharatquant.supervisor.plist"

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"
sed "s|__ROOT__|$ROOT|g" "$PLIST_SRC" > "$PLIST_DST"

launchctl bootout "gui/$(id -u)/com.bharatquant.supervisor" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl enable "gui/$(id -u)/com.bharatquant.supervisor"
launchctl kickstart -k "gui/$(id -u)/com.bharatquant.supervisor"

echo "Installed $PLIST_DST — supervisor will auto-start on login and restart on crash."
echo "Logs: $ROOT/logs/launchd-supervisor.log"
echo "Dashboard: http://127.0.0.1:8080/dashboard"
