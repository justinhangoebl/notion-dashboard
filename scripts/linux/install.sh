#!/usr/bin/env bash
# Installs the dashboard into .venv in the project folder and adds it to
# the application menu.
#   scripts/linux/install.sh          # dashboard only
#   scripts/linux/install.sh --voice  # with voice notes
set -euo pipefail

cd "$(dirname "$0")/../.."
PROJECT="$(pwd)"

TARGET="."
if [[ "${1:-}" == "--voice" ]]; then
    TARGET=".[voice]"
fi

echo "Installing PhD Notion Dashboard..."

if ! command -v python3 >/dev/null; then
    echo "python3 not found. Install Python 3.11+ with your package manager." >&2
    exit 1
fi

if [[ ! -d .venv ]]; then
    echo "Creating virtual environment..."
    if ! python3 -m venv .venv; then
        echo "Couldn't create a virtual environment. On Debian/Ubuntu: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

echo "Installing Python packages..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "$TARGET"

# ---- application menu entry --------------------------------------------

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
sed -e "s|@EXEC@|$PROJECT/.venv/bin/notion-dashboard|" \
    -e "s|@ICON@|$PROJECT/src/notion_dashboard/assets/icon.png|" \
    scripts/linux/notion-dashboard.desktop.in > "$APPS/notion-dashboard.desktop"
echo "Added to the application menu: $APPS/notion-dashboard.desktop"

# ---- system libraries ---------------------------------------------------

# Qt's X11 plugin links against xcb libraries that minimal installs lack;
# voice notes need PortAudio. Ask the plugin itself what's missing.
QXCB="$(.venv/bin/python -c 'import PyQt6, pathlib; print(next(pathlib.Path(PyQt6.__file__).parent.rglob("libqxcb.so")))' 2>/dev/null || true)"
missing=()
if [[ -n "$QXCB" ]]; then
    mapfile -t missing < <(ldd "$QXCB" 2>/dev/null | awk '/not found/ {print $1}' | sort -u)
fi
if [[ "$TARGET" == ".[voice]" ]] && ! ldconfig -p 2>/dev/null | grep -q libportaudio.so; then
    missing+=("libportaudio.so.2")
fi

echo
echo "Installation complete."
if (( ${#missing[@]} )); then
    echo
    echo "Missing system libraries: ${missing[*]}"
    echo "  Debian/Ubuntu: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libportaudio2"
    echo "  Fedora:        sudo dnf install xcb-util-cursor libxkbcommon-x11 xcb-util-wm xcb-util-keysyms portaudio"
    echo "  Arch:          sudo pacman -S xcb-util-cursor libxkbcommon-x11 xcb-util-wm xcb-util-keysyms portaudio"
fi
echo
echo "Next:"
echo "  1. Start:     .venv/bin/notion-dashboard   (or from the application menu)"
echo "  2. Autostart: scripts/linux/install-autostart.sh"
