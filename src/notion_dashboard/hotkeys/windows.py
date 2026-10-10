"""Windows hotkeys via the Win32 RegisterHotKey API: the registered
combinations arrive as WM_HOTKEY messages in Qt's native event loop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, Qt
from PyQt6.QtWidgets import QApplication

from notion_dashboard.hotkeys import SPECIAL_KEYS, Combination, GlobalHotkeys

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


def to_win32(combination: Combination) -> tuple[int, int]:
    """(modifier flags, virtual-key code)"""

    modifiers = (
        (MOD_CONTROL if combination.ctrl else 0)
        | (MOD_ALT if combination.alt else 0)
        | (MOD_SHIFT if combination.shift else 0)
        | (MOD_WIN if combination.meta else 0)
    )

    key = combination.key
    value = key.value
    if Qt.Key.Key_A.value <= value <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= value <= Qt.Key.Key_9.value:
        vk = value  # Qt and Win32 share ASCII codes for letters and digits
    elif Qt.Key.Key_F1.value <= value <= Qt.Key.Key_F24.value:
        vk = 0x70 + value - Qt.Key.Key_F1.value
    else:
        vk = SPECIAL_KEYS[key][0]

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


class WindowsHotkeys(GlobalHotkeys):
    def __init__(self, app: QApplication):
        super().__init__(app)

        # Kept on self: the filter is only referenced from C++ otherwise,
        # and Python would garbage-collect it while Qt still calls it.
        self._filter = _HotkeyFilter(self._dispatch)
        app.installNativeEventFilter(self._filter)

    def _register(self, hotkey_id: int, combination: Combination) -> bool:
        modifiers, vk = to_win32(combination)
        return bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk))

    def _unregister(self, hotkey_id: int):
        ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
