#!/usr/bin/env bash
# Starts the dashboard when you log in (XDG autostart).
set -euo pipefail

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

if [[ ! -f "$APPS/notion-dashboard.desktop" ]]; then
    echo "Run scripts/linux/install.sh first." >&2
    exit 1
fi

mkdir -p "$AUTOSTART"
cp "$APPS/notion-dashboard.desktop" "$AUTOSTART/notion-dashboard.desktop"
echo "Installed: $AUTOSTART/notion-dashboard.desktop"
echo "The dashboard will start automatically when you log in."
