#!/usr/bin/env bash
set -euo pipefail

FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/notion-dashboard.desktop"

if [[ -f "$FILE" ]]; then
    rm "$FILE"
    echo "Removed the dashboard from autostart."
else
    echo "Autostart entry was not installed."
fi
