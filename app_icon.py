"""The app icon: a violet-to-blue tile with a white checkmark.

Drawn in code so it is sharp at every size. Deliberately unlike Notion's
black-and-white "N" so the two are easy to tell apart in the taskbar.

Run `python app_icon.py` to (re)write assets/icon.ico and assets/icon.png,
used by the Windows Startup shortcut.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

ASSETS = Path(__file__).resolve().parent / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def paint_icon(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    inset = size * 0.04
    tile = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)

    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0.0, QColor("#8b5cf6"))
    gradient.setColorAt(1.0, QColor("#2383e2"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    radius = size * 0.24
    painter.drawRoundedRect(tile, radius, radius)

    check = QPainterPath(QPointF(size * 0.28, size * 0.52))
    check.lineTo(QPointF(size * 0.44, size * 0.67))
    check.lineTo(QPointF(size * 0.73, size * 0.35))

    pen = QPen(QColor("white"), max(1.6, size * 0.11))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(check)

    painter.end()
    return image


def app_icon() -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(QPixmap.fromImage(paint_icon(size)))
    return icon


def write_assets():
    ASSETS.mkdir(exist_ok=True)
    paint_icon(256).save(str(ASSETS / "icon.ico"))
    paint_icon(256).save(str(ASSETS / "icon.png"))


if __name__ == "__main__":
    from PyQt6.QtGui import QGuiApplication

    app = QGuiApplication(sys.argv)
    write_assets()
    print(f"Wrote {ASSETS / 'icon.ico'} and {ASSETS / 'icon.png'}")
