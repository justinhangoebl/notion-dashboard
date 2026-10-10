"""System-wide hotkeys via the Win32 RegisterHotKey API.

Only the registered combinations reach the app (as WM_HOTKEY messages);
there is no keyboard hook, so nothing else you type is observed.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

# name -> (label shown in Settings, default combination)
HOTKEY_ACTIONS = {
    "new_todo": ("New TODO (voice)", "Ctrl+Alt+N"),
    "toggle_dashboard": ("Show / hide dashboard", "Ctrl+Alt+D"),
    "toggle_clock": ("Clock in / out", "Ctrl+Alt+W"),
}

WM_HOTKEY = 0x0312
VK_ESCAPE = 0x1B
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_SPECIAL_KEYS = {
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Enter: 0x0D,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Comma: 0xBC,
    Qt.Key.Key_Period: 0xBE,
    Qt.Key.Key_Minus: 0xBD,
    Qt.Key.Key_Plus: 0xBB,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """"Ctrl+Alt+N" -> (Win32 modifier flags, virtual-key code).

    Returns None for an empty, unsupported, or modifier-less combination
    (a bare key would be taken away from every other app).
    """

    sequence = QKeySequence.fromString(text or "", QKeySequence.SequenceFormat.PortableText)
    if sequence.isEmpty():
        return None

    combination = sequence[0]
    qt_modifiers = combination.keyboardModifiers()
    key = combination.key()

    modifiers = 0
    if qt_modifiers & Qt.KeyboardModifier.ControlModifier:
        modifiers |= MOD_CONTROL
    if qt_modifiers & Qt.KeyboardModifier.AltModifier:
        modifiers |= MOD_ALT
    if qt_modifiers & Qt.KeyboardModifier.ShiftModifier:
        modifiers |= MOD_SHIFT
    if qt_modifiers & Qt.KeyboardModifier.MetaModifier:
        modifiers |= MOD_WIN

    if not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None

    value = key.value
    if Qt.Key.Key_A.value <= value <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= value <= Qt.Key.Key_9.value:
        vk = value  # Qt and Win32 share ASCII codes for letters and digits
    elif Qt.Key.Key_F1.value <= value <= Qt.Key.Key_F24.value:
        vk = 0x70 + value - Qt.Key.Key_F1.value
    elif key in _SPECIAL_KEYS:
        vk = _SPECIAL_KEYS[key]
    else:
        return None

    return modifiers, vk


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey):
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._on_hotkey(int(msg.wParam))
                return True, 0
        return False, 0


class GlobalHotkeys(QObject):
    """Registers named hotkeys and emits `triggered(name)` when pressed."""

    triggered = pyqtSignal(str)

    def __init__(self, app: QApplication):
        super().__init__(app)
        self._ids: dict[int, str] = {}
        self._next_id = 1
        self._enabled = sys.platform == "win32"

        # Kept on self: the filter is only referenced from C++ otherwise,
        # and Python would garbage-collect it while Qt still calls it.
        self._filter = _HotkeyFilter(self._dispatch)
        if self._enabled:
            app.installNativeEventFilter(self._filter)

    def apply(self, hotkeys: dict[str, str]) -> list[str]:
        """Replace all registrations. Returns human-readable problems,
        e.g. a combination already taken by another app."""

        self.unregister_all()
        if not self._enabled:
            return []

        problems = []
        for name, text in hotkeys.items():
            if not text:
                continue

            label = HOTKEY_ACTIONS.get(name, (name, ""))[0]
            parsed = parse_hotkey(text)
            if parsed is None:
                problems.append(f"{label}: \"{text}\" needs Ctrl, Alt or Win plus a key")
                continue

            modifiers, vk = parsed
            hotkey_id = self._next_id
            self._next_id += 1

            if ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
                self._ids[hotkey_id] = name
            else:
                problems.append(f"{label}: {text} is already used by another app")

        return problems

    def add_temporary(self, name: str, modifiers: int, vk: int) -> bool:
        """Register a short-lived hotkey outside the configured set, e.g.
        a bare Esc while a recording is running. Remove it with remove()."""

        if not self._enabled or name in self._ids.values():
            return False
        hotkey_id = self._next_id
        self._next_id += 1
        if ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk):
            self._ids[hotkey_id] = name
            return True
        return False

    def remove(self, name: str):
        for hotkey_id, registered in list(self._ids.items()):
            if registered == name:
                if self._enabled:
                    ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
                del self._ids[hotkey_id]

    def unregister_all(self):
        if self._enabled:
            for hotkey_id in self._ids:
                ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self._ids.clear()

    def registered(self) -> dict[int, str]:
        return dict(self._ids)

    def _dispatch(self, hotkey_id: int):
        name = self._ids.get(hotkey_id)
        if name is not None:
            self.triggered.emit(name)


def hotkeys_from_config(config: dict) -> dict[str, str]:
    """Configured hotkeys, falling back to defaults for missing entries.
    An empty string in the config means "disabled"."""

    configured = config.get("hotkeys") or {}
    return {
        name: configured[name] if configured.get(name) is not None else default
        for name, (_label, default) in HOTKEY_ACTIONS.items()
    }
