"""Linux/X11 hotkeys via XGrabKey on the root window (python-xlib).

Like RegisterHotKey on Windows this is an exclusive grab of just these
combinations: X delivers them to us and to nobody else, and every other
key press still goes to the focused app unseen. Events are read in the Qt
event loop through a QSocketNotifier on the X connection, so no thread.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, QSocketNotifier, Qt, QTimer
from Xlib import X, XK
from Xlib.display import Display
from Xlib.error import BadAccess, CatchError

from notion_dashboard.hotkeys import SPECIAL_KEYS, Combination, GlobalHotkeys

# Lock states that must not stop a hotkey from matching: X reports Caps
# Lock and Num Lock as modifiers, so each grab is made for every mix.
CAPS_LOCK = X.LockMask
NUM_LOCK = X.Mod2Mask
IGNORED_MASKS = (0, CAPS_LOCK, NUM_LOCK, CAPS_LOCK | NUM_LOCK)

# Held keys auto-repeat as press/release pairs; presses closer together
# than this count as one (Win32 does the same via MOD_NOREPEAT).
REPEAT_SECONDS = 0.35


def to_keysym(key: Qt.Key) -> int:
    value = key.value
    if Qt.Key.Key_A.value <= value <= Qt.Key.Key_Z.value:
        return ord(chr(value).lower())
    if Qt.Key.Key_0.value <= value <= Qt.Key.Key_9.value:
        return value
    if Qt.Key.Key_F1.value <= value <= Qt.Key.Key_F24.value:
        return XK.XK_F1 + value - Qt.Key.Key_F1.value
    return SPECIAL_KEYS[key][1]


def to_mask(combination: Combination) -> int:
    return (
        (X.ControlMask if combination.ctrl else 0)
        | (X.Mod1Mask if combination.alt else 0)
        | (X.ShiftMask if combination.shift else 0)
        | (X.Mod4Mask if combination.meta else 0)
    )


class X11Hotkeys(GlobalHotkeys):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._display = Display()
        self._root = self._display.screen().root
        self._grabs: dict[int, tuple[int, int]] = {}  # id -> (keycode, mask)
        self._last_press: dict[int, float] = {}

        self._notifier = QSocketNotifier(self._display.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read_events)

    def _register(self, hotkey_id: int, combination: Combination) -> bool:
        keycode = self._display.keysym_to_keycode(to_keysym(combination.key))
        if not keycode:
            return False
        mask = to_mask(combination)

        error = CatchError(BadAccess)
        for extra in IGNORED_MASKS:
            self._root.grab_key(keycode, mask | extra, True, X.GrabModeAsync, X.GrabModeAsync, onerror=error)
        self._sync()

        if error.get_error():  # another client already holds it
            self._ungrab(keycode, mask)
            return False

        self._grabs[hotkey_id] = (keycode, mask)
        return True

    def _unregister(self, hotkey_id: int):
        grab = self._grabs.pop(hotkey_id, None)
        if grab:
            self._ungrab(*grab)

    def _ungrab(self, keycode: int, mask: int):
        for extra in IGNORED_MASKS:
            self._root.ungrab_key(keycode, mask | extra)
        self._sync()

    def _sync(self):
        self._display.sync()
        # sync() may have pulled key events off the socket into python-xlib's
        # queue, where the socket notifier won't see them.
        QTimer.singleShot(0, self._read_events)

    def _read_events(self):
        while self._display.pending_events():
            event = self._display.next_event()
            if event.type != X.KeyPress:
                continue

            state = event.state & ~(CAPS_LOCK | NUM_LOCK)
            for hotkey_id, (keycode, mask) in self._grabs.items():
                if keycode == event.detail and mask == state:
                    now = time.monotonic()
                    if now - self._last_press.get(hotkey_id, 0.0) >= REPEAT_SECONDS:
                        self._dispatch(hotkey_id)
                    self._last_press[hotkey_id] = now
                    break
