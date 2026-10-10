"""System-wide hotkeys.

Only the registered combinations reach the app; there is no keyboard hook,
so nothing else you type is observed. The platform does the work:

  Windows        RegisterHotKey (hotkeys/windows.py)
  Linux on X11   XGrabKey on the root window (hotkeys/x11.py)
  Wayland        no global hotkeys for apps - bind the desktop's own
                 shortcuts to `notion-dashboard --action <name>` instead

create_hotkeys() picks the backend; GlobalHotkeys is the shared interface.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeySequence

# name -> (label shown in Settings, default combination)
HOTKEY_ACTIONS = {
    "new_todo": ("New TODO (voice or typed)", "Ctrl+Alt+N"),
    "toggle_dashboard": ("Show / hide dashboard", "Ctrl+Alt+D"),
    "toggle_clock": ("Clock in / out", "Ctrl+Alt+W"),
}


@dataclass(frozen=True)
class Combination:
    ctrl: bool
    alt: bool
    shift: bool
    meta: bool  # Win on Windows, Super on Linux
    key: Qt.Key


def parse_hotkey(text: str, allow_bare: bool = False) -> Combination | None:
    """"Ctrl+Alt+N" -> Combination.

    Returns None for an empty or unsupported combination, and for one
    without Ctrl, Alt or Win/Super unless `allow_bare` (a bare key would be
    taken away from every other app).
    """

    sequence = QKeySequence.fromString(text or "", QKeySequence.SequenceFormat.PortableText)
    if sequence.isEmpty():
        return None

    combination = sequence[0]
    mods = combination.keyboardModifiers()
    parsed = Combination(
        ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
        alt=bool(mods & Qt.KeyboardModifier.AltModifier),
        shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
        meta=bool(mods & Qt.KeyboardModifier.MetaModifier),
        key=combination.key(),
    )

    if not (allow_bare or parsed.ctrl or parsed.alt or parsed.meta):
        return None
    if not is_supported_key(parsed.key):
        return None
    return parsed


def is_supported_key(key: Qt.Key) -> bool:
    value = key.value
    return (
        Qt.Key.Key_A.value <= value <= Qt.Key.Key_Z.value
        or Qt.Key.Key_0.value <= value <= Qt.Key.Key_9.value
        or Qt.Key.Key_F1.value <= value <= Qt.Key.Key_F24.value
        or key in SPECIAL_KEYS
    )


# Non-alphanumeric keys a hotkey may use: Qt key -> (Win32 VK, X11 keysym)
SPECIAL_KEYS = {
    Qt.Key.Key_Escape: (0x1B, 0xFF1B),
    Qt.Key.Key_Space: (0x20, 0x0020),
    Qt.Key.Key_Return: (0x0D, 0xFF0D),
    Qt.Key.Key_Enter: (0x0D, 0xFF8D),
    Qt.Key.Key_Tab: (0x09, 0xFF09),
    Qt.Key.Key_Insert: (0x2D, 0xFF63),
    Qt.Key.Key_Delete: (0x2E, 0xFFFF),
    Qt.Key.Key_Home: (0x24, 0xFF50),
    Qt.Key.Key_End: (0x23, 0xFF57),
    Qt.Key.Key_PageUp: (0x21, 0xFF55),
    Qt.Key.Key_PageDown: (0x22, 0xFF56),
    Qt.Key.Key_Left: (0x25, 0xFF51),
    Qt.Key.Key_Up: (0x26, 0xFF52),
    Qt.Key.Key_Right: (0x27, 0xFF53),
    Qt.Key.Key_Down: (0x28, 0xFF54),
    Qt.Key.Key_Comma: (0xBC, 0x002C),
    Qt.Key.Key_Period: (0xBE, 0x002E),
    Qt.Key.Key_Minus: (0xBD, 0x002D),
    Qt.Key.Key_Plus: (0xBB, 0x002B),
}


class GlobalHotkeys(QObject):
    """Registers named hotkeys and emits `triggered(name)` when pressed.

    Backends implement _register()/_unregister(); this class keeps track
    of which id belongs to which name.
    """

    triggered = pyqtSignal(str)

    # Shown in Settings: why hotkeys can't work at all here, or a caveat.
    unavailable_reason = ""
    hint = ""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._ids: dict[int, str] = {}
        self._next_id = 1

    # ---- backend interface ------------------------------------------------

    def _register(self, hotkey_id: int, combination: Combination) -> bool:
        return False

    def _unregister(self, hotkey_id: int):
        pass

    # ---- public -----------------------------------------------------------

    def apply(self, hotkeys: dict[str, str]) -> list[str]:
        """Replace all registrations. Returns human-readable problems,
        e.g. a combination already taken by another app."""

        self.unregister_all()
        if self.unavailable_reason:
            return []

        problems = []
        for name, text in hotkeys.items():
            if not text:
                continue

            label = HOTKEY_ACTIONS.get(name, (name, ""))[0]
            combination = parse_hotkey(text)
            if combination is None:
                problems.append(f'{label}: "{text}" needs Ctrl, Alt or Win plus a key')
            elif not self._add(name, combination):
                problems.append(f"{label}: {text} is already used by another app")

        return problems

    def add_temporary(self, name: str, text: str) -> bool:
        """Register a short-lived hotkey outside the configured set, e.g.
        a bare Esc while a recording is running. Remove it with remove()."""

        combination = parse_hotkey(text, allow_bare=True)
        if self.unavailable_reason or combination is None or name in self._ids.values():
            return False
        return self._add(name, combination)

    def remove(self, name: str):
        for hotkey_id, registered in list(self._ids.items()):
            if registered == name:
                self._unregister(hotkey_id)
                del self._ids[hotkey_id]

    def unregister_all(self):
        for hotkey_id in self._ids:
            self._unregister(hotkey_id)
        self._ids.clear()

    def registered(self) -> dict[int, str]:
        return dict(self._ids)

    # ---- helpers ----------------------------------------------------------

    def _add(self, name: str, combination: Combination) -> bool:
        hotkey_id = self._next_id
        self._next_id += 1
        if self._register(hotkey_id, combination):
            self._ids[hotkey_id] = name
            return True
        return False

    def _dispatch(self, hotkey_id: int):
        name = self._ids.get(hotkey_id)
        if name is not None:
            self.triggered.emit(name)


class UnavailableHotkeys(GlobalHotkeys):
    def __init__(self, reason: str, parent: QObject | None = None):
        super().__init__(parent)
        self.unavailable_reason = reason


WAYLAND_HINT = (
    "Wayland doesn't let apps set global hotkeys. Add them in your desktop's keyboard "
    "settings instead, running e.g.  notion-dashboard --action new_todo"
)


def create_hotkeys(app: QGuiApplication) -> GlobalHotkeys:
    if sys.platform == "win32":
        from notion_dashboard.hotkeys.windows import WindowsHotkeys

        return WindowsHotkeys(app)

    if QGuiApplication.platformName() == "xcb":
        try:
            from notion_dashboard.hotkeys.x11 import X11Hotkeys

            hotkeys = X11Hotkeys(app)
        except Exception as exc:  # python-xlib missing, no X display, ...
            return UnavailableHotkeys(f"Global hotkeys unavailable: {exc}", app)

        # Under XWayland, X11 grabs only fire while an X11 window has focus.
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            hotkeys.hint = WAYLAND_HINT
        return hotkeys

    return UnavailableHotkeys(WAYLAND_HINT, app)


def hotkeys_from_config(config: dict) -> dict[str, str]:
    """Configured hotkeys, falling back to defaults for missing entries.
    An empty string in the config means "disabled"."""

    configured = config.get("hotkeys") or {}
    return {
        name: configured[name] if configured.get(name) is not None else default
        for name, (_label, default) in HOTKEY_ACTIONS.items()
    }
