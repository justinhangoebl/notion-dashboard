"""Icon glyphs for buttons, section headers and labels.

Icons are drawn from an icon font rather than Unicode symbols (↻ ⚙ □ ×),
which render at wildly different sizes and baselines depending on the
glyph and make a row of buttons look misaligned.

Windows ships Segoe MDL2 Assets. Elsewhere the bundled Material Icons font
(assets/fonts, Apache 2.0) is used; call load_icon_font() once the
QApplication exists so Qt knows about it. Set NOTION_DASHBOARD_ICONS=material
to use the bundled font on Windows too (handy for checking the Linux look).
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtGui import QFontDatabase

from notion_dashboard.paths import ASSETS

USE_SEGOE = sys.platform == "win32" and os.environ.get("NOTION_DASHBOARD_ICONS", "") != "material"

ICON_FONT = "Segoe MDL2 Assets" if USE_SEGOE else "Material Icons"


def _glyph(segoe: int, material: int) -> str:
    return chr(segoe if USE_SEGOE else material)


ICON_REFRESH = _glyph(0xE72C, 0xE5D5)
ICON_SETTINGS = _glyph(0xE713, 0xE8B8)
ICON_MINIMIZE = _glyph(0xE921, 0xE15B)
ICON_MAXIMIZE = _glyph(0xE922, 0xE3C6)
ICON_RESTORE = _glyph(0xE923, 0xE3E0)
ICON_CLOSE = _glyph(0xE8BB, 0xE5CD)

ICON_CALENDAR = _glyph(0xE787, 0xE935)
ICON_CLOCK = _glyph(0xE823, 0xE8B5)
ICON_LOCATION = _glyph(0xE819, 0xE55F)
ICON_LINK = _glyph(0xE71B, 0xE157)
ICON_FLAG = _glyph(0xE7C1, 0xE153)
ICON_WORK = _glyph(0xE821, 0xE8F9)
ICON_PREV = _glyph(0xE76B, 0xE5CB)
ICON_NEXT = _glyph(0xE76C, 0xE5CC)

ICON_TODO = _glyph(0xE73A, 0xE2E6)
ICON_ADD = _glyph(0xE710, 0xE145)
ICON_EDIT = _glyph(0xE70F, 0xE3C9)

ICON_DASHBOARD = _glyph(0xE80F, 0xE871)
ICON_MICROPHONE = _glyph(0xE720, 0xE029)
ICON_KEYBOARD = _glyph(0xE765, 0xE312)


def load_icon_font():
    if not USE_SEGOE:
        QFontDatabase.addApplicationFont(str(ASSETS / "fonts" / "MaterialIcons-Regular.ttf"))
