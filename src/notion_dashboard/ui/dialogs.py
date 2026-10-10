"""Notion-styled dialogs for adding a meeting or a TODO.

Qt's native composite inputs (QDateEdit, QTimeEdit, QComboBox) can't be
reliably restyled with QSS, so every property value here is a flat
QPushButton or QLineEdit, and every picker is a custom popup (_Popup).
"""

from __future__ import annotations

import html
import math
from datetime import date, datetime, time

from PyQt6.QtCore import QDate, QPointF, QRectF, QTime, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QTextCharFormat
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from notion_dashboard.ui.icons import (
    ICON_CALENDAR,
    ICON_CLOCK,
    ICON_FLAG,
    ICON_FONT,
    ICON_LINK,
    ICON_LOCATION,
    ICON_NEXT,
    ICON_PREV,
    ICON_WORK,
)
from notion_dashboard.ui.title_bar import FramelessDialog


# Notion's dark-mode select-tag colors.
TAG_COLORS = {
    "high": "#6e3630",
    "medium": "#89632a",
    "low": "#28456c",
}



def make_pill(text: str, colors: dict) -> QLabel:
    """A small Notion select tag. Transparent to the mouse so it never
    steals clicks from the row or button it sits in."""

    pill = QLabel(text)
    pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    pill.setStyleSheet(
        f"""
        QLabel {{
            background: {TAG_COLORS.get(text.strip().casefold(), colors["hover"])};
            color: rgba(255, 255, 255, 0.9);
            border-radius: 3px;
            padding: 1px 6px;
            font-family: "Segoe UI";
            font-size: 8pt;
        }}
        """
    )
    return pill


def _icon_label_html(icon: str, text: str) -> str:
    return (
        f'<span style="font-family:\'{ICON_FONT}\'; font-size:8pt;">{icon}</span>'
        f"&nbsp;&nbsp;{html.escape(text)}"
    )


def _property_row(icon: str, label: str, widget: QWidget) -> QWidget:
    """An "icon label | value" row, like a property on a Notion page. The
    value always spans the rest of the row, so the whole row is clickable."""

    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    label_widget = QLabel(_icon_label_html(icon, label))
    label_widget.setObjectName("propLabel")
    label_widget.setTextFormat(Qt.TextFormat.RichText)
    label_widget.setFixedWidth(96)
    layout.addWidget(label_widget)

    layout.addWidget(widget, stretch=1)
    return row


def _divider(colors: dict) -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {colors['border']}; border: none;")
    return line


def _mute_placeholder(widget: QWidget, colors: dict):
    """Placeholder text uses QPalette.PlaceholderText, which QSS can't set.
    The color is also stored as a property because the stylesheet polish
    on show() resets the palette; FramelessDialog.showEvent reapplies it."""

    widget.setProperty("_placeholderColor", colors["muted"])
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["muted"]))
    widget.setPalette(palette)


# ==============================================================
# POPUP
# ==============================================================


class _Popup(QWidget):
    """A frameless popup with one rounded border.

    The border is set on a single named QFrame. A generic `QWidget { border }`
    rule would also draw a border around every widget inside the popup.
    """

    def __init__(self, colors: dict, content: QWidget):
        super().__init__(
            None,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QFrame()
        frame.setObjectName("popupFrame")
        frame.setStyleSheet(
            f"""
            QFrame#popupFrame {{
                background: {colors["panel"]};
                border: 1px solid {colors["border"]};
                border-radius: 8px;
            }}
            """
        )
        outer.addWidget(frame)

        inner = QVBoxLayout(frame)
        inner.setContentsMargins(4, 4, 4, 4)
        inner.setSpacing(0)
        inner.addWidget(content)

    def show_below(self, anchor: QWidget, width: int | None = None):
        if width is not None:
            self.setFixedWidth(width)
        self.adjustSize()

        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        pos.setY(pos.y() + 4)

        screen = anchor.screen().availableGeometry()
        if pos.y() + self.height() > screen.bottom():
            pos.setY(anchor.mapToGlobal(anchor.rect().topLeft()).y() - self.height() - 4)
        if pos.x() + self.width() > screen.right():
            pos.setX(screen.right() - self.width())

        self.move(pos)

        # A parentless popup is otherwise referenced only from C++ (its
        # child widgets and signal connections), which Python's cyclic GC
        # can't see: it would collect the popup's wrappers while it is
        # still on screen and crash the next paint. The anchor keeps it.
        anchor._open_popup_ref = self
        self.show()


# ==============================================================
# CALENDAR
# ==============================================================


def _calendar_stylesheet(colors: dict) -> str:
    return f"""
        QCalendarWidget, QCalendarWidget QWidget {{
            background: transparent;
            border: none;
        }}

        QCalendarWidget QAbstractItemView {{
            background: {colors["panel"]};
            alternate-background-color: {colors["panel"]};
            color: {colors["text"]};
            selection-background-color: {colors["accent"]};
            selection-color: white;
            outline: none;
            font-family: "Segoe UI";
            font-size: 9pt;
        }}

        QCalendarWidget QAbstractItemView:disabled {{
            color: {colors["muted"]};
        }}

        QLabel#calHeaderLabel {{
            color: {colors["text"]};
            font-family: "Segoe UI";
            font-size: 10pt;
            font-weight: 700;
        }}

        QPushButton#calTodayButton {{
            border: none;
            border-radius: 4px;
            color: {colors["muted"]};
            font-family: "Segoe UI";
            font-size: 8pt;
            padding: 3px 8px;
        }}

        QPushButton#calTodayButton:hover {{
            background: {colors["hover"]};
            color: {colors["text"]};
        }}

        QPushButton#calNavButton {{
            border: none;
            border-radius: 4px;
            color: {colors["muted"]};
            font-family: "{ICON_FONT}";
            font-size: 8pt;
            padding: 0;
        }}

        QPushButton#calNavButton:hover {{
            background: {colors["hover"]};
            color: {colors["text"]};
        }}
    """


class NotionCalendar(QCalendarWidget):
    """QCalendarWidget with the native navigation bar replaced by a
    "Sep 2026 · Today · ‹ ›" header.

    The weekday row is not a QHeaderView; QCalendarWidget draws it as the
    model's first row, using setHeaderTextFormat() plus any per-weekday
    formats. Both are set explicitly below.
    """

    def __init__(self, colors: dict, parent: QWidget | None = None):
        super().__init__(parent)

        self.setStyleSheet(_calendar_stylesheet(colors))
        self.setNavigationBarVisible(False)
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)

        header_format = QTextCharFormat()
        header_format.setBackground(QColor(colors["panel"]))
        header_format.setForeground(QColor(colors["muted"]))
        self.setHeaderTextFormat(header_format)

        # Per-weekday formats also apply to the header row, so a foreground
        # set here would override the header color. An empty format clears
        # Qt's default red weekend text without touching the header.
        for day in (
            Qt.DayOfWeek.Monday,
            Qt.DayOfWeek.Tuesday,
            Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday,
            Qt.DayOfWeek.Friday,
            Qt.DayOfWeek.Saturday,
            Qt.DayOfWeek.Sunday,
        ):
            self.setWeekdayTextFormat(day, QTextCharFormat())

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 2, 2, 6)
        header_layout.setSpacing(2)

        self._label = QLabel()
        self._label.setObjectName("calHeaderLabel")
        header_layout.addWidget(self._label)
        header_layout.addStretch(1)

        today_button = QPushButton("Today")
        today_button.setObjectName("calTodayButton")
        today_button.setCursor(Qt.CursorShape.PointingHandCursor)
        today_button.clicked.connect(self._go_to_today)
        header_layout.addWidget(today_button)

        for icon, slot in ((ICON_PREV, self.showPreviousMonth), (ICON_NEXT, self.showNextMonth)):
            button = QPushButton(icon)
            button.setObjectName("calNavButton")
            button.setFixedSize(24, 24)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
            header_layout.addWidget(button)

        layout = self.layout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.insertWidget(0, header)

        self.setFixedSize(260, 250)

        self.currentPageChanged.connect(self._update_label)
        self._update_label(self.yearShown(), self.monthShown())

    def _go_to_today(self):
        today = QDate.currentDate()
        self.setCurrentPage(today.year(), today.month())
        self.setSelectedDate(today)
        self.clicked.emit(today)

    def _update_label(self, year: int, month: int):
        self._label.setText(QDate(year, month, 1).toString("MMM yyyy"))


# ==============================================================
# PROPERTY FIELDS
# ==============================================================


class _FieldButton(QPushButton):
    """Flat, full-width property value that opens a picker on click."""

    def __init__(self, colors: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._colors = colors
        self.setObjectName("fieldButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)
        self.clicked.connect(self._open_popup)

    def _set_empty(self, empty: bool):
        self.setProperty("empty", empty)
        self.style().unpolish(self)
        self.style().polish(self)

    def _open_popup(self):
        raise NotImplementedError


class DateButton(_FieldButton):
    def __init__(self, colors: dict, clearable: bool = False, parent: QWidget | None = None):
        super().__init__(colors, parent)
        self._date: QDate | None = None
        self._clearable = clearable
        self._refresh()

    def date(self) -> QDate | None:
        return self._date

    def setDate(self, value: QDate | None):
        self._date = value
        self._refresh()

    def _refresh(self):
        self._set_empty(self._date is None)
        self.setText(self._date.toString("MMMM d, yyyy") if self._date else "Empty")

    def _open_popup(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        calendar = NotionCalendar(self._colors)
        if self._date is not None:
            calendar.setSelectedDate(self._date)
        layout.addWidget(calendar)

        popup = _Popup(self._colors, content)
        calendar.clicked.connect(lambda value: self._pick(value, popup))

        if self._clearable:
            clear = QPushButton("Clear")
            clear.setCursor(Qt.CursorShape.PointingHandCursor)
            clear.setStyleSheet(
                f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    color: {self._colors["muted"]};
                    font-family: "Segoe UI";
                    font-size: 9pt;
                    text-align: left;
                    padding: 6px 8px;
                }}
                QPushButton:hover {{
                    background: {self._colors["hover"]};
                    color: {self._colors["text"]};
                }}
                """
            )
            clear.clicked.connect(lambda: self._pick(None, popup))
            layout.addWidget(clear)

        popup.show_below(self)

    def _pick(self, value: QDate | None, popup: QWidget):
        self.setDate(value)
        popup.close()


class ClockDial(QWidget):
    """A radial clock face. Hours use two rings (1-12 outside, 00 and
    13-23 inside); minutes snap to 5-minute steps on a single ring."""

    changed = pyqtSignal()
    released = pyqtSignal()

    SIZE = 232

    def __init__(self, colors: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._colors = colors
        self.mode = "hour"
        self.hour = 0
        self.minute = 0
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_mode(self, mode: str):
        self.mode = mode
        self.update()

    # ---- geometry --------------------------------------------------

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def _outer_radius(self) -> float:
        return self.width() / 2 - 22

    def _inner_radius(self) -> float:
        return self.width() / 2 - 56

    def _point(self, index: int, count: int, radius: float) -> QPointF:
        angle = math.radians(index * 360 / count)
        center = self._center()
        return QPointF(center.x() + radius * math.sin(angle), center.y() - radius * math.cos(angle))

    def _selected_point(self) -> QPointF:
        if self.mode == "minute":
            return self._point(self.minute, 60, self._outer_radius())
        if 1 <= self.hour <= 12:
            return self._point(self.hour % 12, 12, self._outer_radius())
        return self._point(self.hour % 12, 12, self._inner_radius())

    # ---- painting --------------------------------------------------

    def paintEvent(self, event):
        colors = self._colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = self._center()
        face_radius = self.width() / 2 - 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["hover"]))
        painter.drawEllipse(center, face_radius, face_radius)

        selected = self._selected_point()
        accent = QColor(colors["accent"])

        painter.setPen(QPen(accent, 2))
        painter.drawLine(center, selected)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(center, 3, 3)
        painter.drawEllipse(selected, 16, 16)

        if self.mode == "hour":
            outer = [(i % 12, str(i), 1 <= self.hour <= 12 and self.hour == i) for i in range(1, 13)]
            inner = [
                (i % 12, f"{i:02d}", self.hour == i)
                for i in [0] + list(range(13, 24))
            ]
            self._draw_labels(painter, outer, self._outer_radius(), 10, colors["text"])
            self._draw_labels(painter, inner, self._inner_radius(), 8, colors["muted"])
        else:
            labels = [(m, f"{m:02d}", self.minute == m) for m in range(0, 60, 5)]
            self._draw_labels(painter, labels, self._outer_radius(), 10, colors["text"], count=60)

        painter.end()

    def _draw_labels(self, painter, labels, radius, size, color, count=12):
        font = QFont("Segoe UI")
        font.setPointSize(size)
        painter.setFont(font)

        for index, text, is_selected in labels:
            point = self._point(index, count, radius)
            rect = QRectF(point.x() - 16, point.y() - 16, 32, 32)
            painter.setPen(QColor("white") if is_selected else QColor(color))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # ---- input -----------------------------------------------------

    def _pick_at(self, pos):
        center = self._center()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        angle = math.degrees(math.atan2(dx, -dy)) % 360

        if self.mode == "minute":
            self.minute = int(round(angle / 30)) % 12 * 5
        else:
            index = int(round(angle / 30)) % 12
            distance = math.hypot(dx, dy)
            inner = distance < (self._outer_radius() + self._inner_radius()) / 2
            if inner:
                self.hour = 0 if index == 0 else index + 12
            else:
                self.hour = 12 if index == 0 else index

        self.update()
        self.changed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick_at(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick_at(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit()


class ClockPicker(QWidget):
    """HH : MM header above a ClockDial. Choosing an hour moves on to
    minutes; choosing a minute finishes."""

    finished = pyqtSignal(QTime)

    def __init__(self, colors: dict, initial: QTime, parent: QWidget | None = None):
        super().__init__(parent)
        self._colors = colors

        self.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                color: {colors["muted"]};
                font-family: "Segoe UI";
                font-size: 20pt;
                font-weight: 600;
                padding: 0 6px;
            }}
            QPushButton:hover {{
                background: {colors["hover"]};
            }}
            QPushButton[active="true"] {{
                color: {colors["accent"]};
            }}
            QLabel {{
                color: {colors["muted"]};
                font-family: "Segoe UI";
                font-size: 20pt;
                font-weight: 600;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addStretch(1)
        self._hour_button = QPushButton()
        self._hour_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hour_button.clicked.connect(lambda: self._set_mode("hour"))
        header.addWidget(self._hour_button)
        header.addWidget(QLabel(":"))
        self._minute_button = QPushButton()
        self._minute_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minute_button.clicked.connect(lambda: self._set_mode("minute"))
        header.addWidget(self._minute_button)
        header.addStretch(1)
        layout.addLayout(header)

        self._dial = ClockDial(colors)
        self._dial.hour = initial.hour()
        self._dial.minute = initial.minute() - initial.minute() % 5
        self._dial.changed.connect(self._refresh)
        self._dial.released.connect(self._on_released)
        layout.addWidget(self._dial, 0, Qt.AlignmentFlag.AlignHCenter)

        self._set_mode("hour")

    def _set_mode(self, mode: str):
        self._dial.set_mode(mode)
        for button, name in ((self._hour_button, "hour"), (self._minute_button, "minute")):
            button.setProperty("active", mode == name)
            button.style().unpolish(button)
            button.style().polish(button)
        self._refresh()

    def _refresh(self):
        self._hour_button.setText(f"{self._dial.hour:02d}")
        self._minute_button.setText(f"{self._dial.minute:02d}")

    def _on_released(self):
        if self._dial.mode == "hour":
            self._set_mode("minute")
        else:
            self.finished.emit(QTime(self._dial.hour, self._dial.minute))


class TimeButton(_FieldButton):
    def __init__(self, colors: dict, initial: QTime, parent: QWidget | None = None):
        super().__init__(colors, parent)
        self._time = initial
        self.setText(initial.toString("HH:mm"))

    def time(self) -> QTime:
        return self._time

    def setTime(self, value: QTime):
        self._time = value
        self.setText(value.toString("HH:mm"))

    def _open_popup(self):
        picker = ClockPicker(self._colors, self._time)
        popup = _Popup(self._colors, picker)
        picker.finished.connect(lambda value: self._pick(value, popup))
        popup.show_below(self)

    def _pick(self, value: QTime, popup: QWidget):
        self.setTime(value)
        popup.close()


class SelectButton(_FieldButton):
    """A Notion select property: a small tag inside a full-width field,
    opening a list of tags to choose from."""

    def __init__(self, colors: dict, options: list[str], value: str = "", parent: QWidget | None = None):
        super().__init__(colors, parent)
        self._options = options
        self._value = value

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 0, 6, 0)
        self._layout.setSpacing(0)
        self._refresh()

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        self._refresh()

    def _refresh(self):
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

        self._set_empty(not self._value)
        if self._value:
            self.setText("")
            self._layout.addWidget(make_pill(self._value, self._colors), 0, Qt.AlignmentFlag.AlignVCenter)
            self._layout.addStretch(1)
        else:
            self.setText("Empty")

    def _open_popup(self):
        colors = self._colors
        content = QWidget()
        content.setStyleSheet(
            f"""
            QPushButton#optionButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#optionButton:hover {{
                background: {colors["hover"]};
            }}
            """
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        popup = _Popup(colors, content)

        for option in self._options:
            button = QPushButton()
            button.setObjectName("optionButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(28)

            row = QHBoxLayout(button)
            row.setContentsMargins(6, 0, 6, 0)
            row.addWidget(make_pill(option, colors), 0, Qt.AlignmentFlag.AlignVCenter)
            row.addStretch(1)

            button.clicked.connect(lambda _=False, o=option: self._pick(o, popup))
            layout.addWidget(button)

        popup.show_below(self, width=max(self.width(), 160))

    def _pick(self, value: str, popup: QWidget):
        self.setValue(value)
        popup.close()


# ==============================================================
# DIALOGS
# ==============================================================


def _dialog_stylesheet(colors: dict) -> str:
    return f"""
        /* The Dashboard stylesheet has a blanket `QWidget {{ background }}`
           rule, and Qt cascades a parent's stylesheet into its child
           dialogs. This dialog's sheet is closer, so this reset wins. */
        QWidget {{
            background: transparent;
            color: {colors["text"]};
            font-family: "Segoe UI";
            font-size: 9pt;
        }}

        QDialog, QWidget#dialogContent {{
            background: {colors["panel"]};
        }}

        QLabel#propLabel {{
            color: {colors["muted"]};
        }}

        QLineEdit#titleInput {{
            background: transparent;
            border: none;
            font-size: 15pt;
            font-weight: 700;
            padding: 2px 0;
        }}

        QLineEdit {{
            background: transparent;
            border: none;
            border-radius: 4px;
            padding: 5px 4px;
        }}

        QLineEdit:hover, QLineEdit:focus {{
            background: {colors["hover"]};
        }}

        QLineEdit#titleInput:hover, QLineEdit#titleInput:focus {{
            background: transparent;
        }}

        QPushButton#fieldButton {{
            background: transparent;
            border: none;
            border-radius: 4px;
            text-align: left;
            padding: 5px 6px;
        }}

        QPushButton#fieldButton:hover {{
            background: {colors["hover"]};
        }}

        QPushButton#fieldButton[empty="true"] {{
            color: {colors["muted"]};
        }}

        QPlainTextEdit {{
            background: transparent;
            border: none;
            padding: 0;
        }}

        QPushButton {{
            background: transparent;
            border: 1px solid {colors["border"]};
            border-radius: 6px;
            padding: 6px 16px;
        }}

        QPushButton:hover {{
            background: {colors["hover"]};
        }}

        QPushButton#saveButton {{
            background: {colors["accent"]};
            border: 1px solid {colors["accent"]};
            color: white;
            font-weight: 600;
        }}

        QPushButton#saveButton:hover {{
            background: {colors["accent_hover"]};
        }}
    """


def _action_buttons(dialog: FramelessDialog, save_text: str, on_save) -> QHBoxLayout:
    buttons = QHBoxLayout()
    buttons.setSpacing(8)
    buttons.addStretch(1)

    cancel_button = QPushButton("Cancel")
    cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel_button.clicked.connect(dialog.reject)
    buttons.addWidget(cancel_button)

    save_button = QPushButton(save_text)
    save_button.setObjectName("saveButton")
    save_button.setCursor(Qt.CursorShape.PointingHandCursor)
    save_button.setDefault(True)
    save_button.clicked.connect(on_save)
    buttons.addWidget(save_button)

    return buttons


def _title_input(placeholder: str, colors: dict) -> QLineEdit:
    title = QLineEdit()
    title.setObjectName("titleInput")
    title.setPlaceholderText(placeholder)
    _mute_placeholder(title, colors)
    return title


def _page_layout(dialog: FramelessDialog) -> QVBoxLayout:
    root = dialog.content_layout
    root.setContentsMargins(24, 16, 24, 18)
    root.setSpacing(2)
    return root


class AddMeetingDialog(FramelessDialog):
    def __init__(self, colors: dict, parent: QWidget | None = None):
        super().__init__("New meeting", colors, parent)

        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(_dialog_stylesheet(colors))
        self.result: dict | None = None

        root = _page_layout(self)

        self.title_edit = _title_input("Untitled", colors)
        root.addWidget(self.title_edit)
        root.addSpacing(10)
        root.addWidget(_divider(colors))
        root.addSpacing(10)

        self.date_button = DateButton(colors)
        self.date_button.setDate(QDate.currentDate())
        root.addWidget(_property_row(ICON_CALENDAR, "Date", self.date_button))

        now = QTime.currentTime()
        start = QTime(now.hour(), 0).addSecs(3600)
        self.start_button = TimeButton(colors, start)
        root.addWidget(_property_row(ICON_CLOCK, "Start", self.start_button))

        self.end_button = TimeButton(colors, start.addSecs(3600))
        root.addWidget(_property_row(ICON_CLOCK, "End", self.end_button))

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Empty")
        _mute_placeholder(self.location_edit, colors)
        root.addWidget(_property_row(ICON_LOCATION, "Location", self.location_edit))

        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("Empty")
        _mute_placeholder(self.link_edit, colors)
        root.addWidget(_property_row(ICON_LINK, "Link", self.link_edit))

        root.addSpacing(18)
        root.addLayout(_action_buttons(self, "Add", self._on_save))

        self.title_edit.setFocus()

    def _on_save(self):
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setFocus()
            return

        qdate = self.date_button.date() or QDate.currentDate()
        day = date(qdate.year(), qdate.month(), qdate.day())

        qstart = self.start_button.time()
        qend = self.end_button.time()

        start = datetime.combine(day, time(qstart.hour(), qstart.minute())).astimezone()
        end = datetime.combine(day, time(qend.hour(), qend.minute())).astimezone()
        if end <= start:
            end = None

        self.result = {
            "title": title,
            "start": start,
            "end": end,
            "location": self.location_edit.text().strip(),
            "link": self.link_edit.text().strip(),
        }
        self.accept()


class AddTodoDialog(FramelessDialog):
    PRIORITIES = ["High", "Medium", "Low"]

    def __init__(self, colors: dict, parent: QWidget | None = None):
        super().__init__("New TODO", colors, parent)

        self.setModal(True)
        self.setFixedWidth(400)
        self.setStyleSheet(_dialog_stylesheet(colors))
        self.result: dict | None = None

        root = _page_layout(self)

        self.title_edit = _title_input("Untitled", colors)
        root.addWidget(self.title_edit)
        root.addSpacing(10)
        root.addWidget(_divider(colors))
        root.addSpacing(10)

        self.due_button = DateButton(colors, clearable=True)
        root.addWidget(_property_row(ICON_CALENDAR, "Due", self.due_button))

        self.priority_button = SelectButton(colors, self.PRIORITIES, "Low")
        root.addWidget(_property_row(ICON_FLAG, "Priority", self.priority_button))

        root.addSpacing(10)
        root.addWidget(_divider(colors))
        root.addSpacing(10)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Add notes...")
        _mute_placeholder(self.notes_edit, colors)
        self.notes_edit.setFixedHeight(110)
        root.addWidget(self.notes_edit)

        root.addSpacing(12)
        root.addLayout(_action_buttons(self, "Add", self._on_save))

        self.title_edit.setFocus()

    def _on_save(self):
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setFocus()
            return

        qdue = self.due_button.date()
        due = date(qdue.year(), qdue.month(), qdue.day()) if qdue is not None else None

        self.result = {
            "title": title,
            "due": due,
            "priority": self.priority_button.value(),
            "content": self.notes_edit.toPlainText().strip(),
        }
        self.accept()


class EditTodoDialog(FramelessDialog):
    """Views/edits an existing TODO's Notion page content."""

    def __init__(self, title: str, content: str, colors: dict, parent: QWidget | None = None):
        super().__init__("Notes", colors, parent)

        self.setModal(True)
        self.setFixedSize(400, 360)
        self.setStyleSheet(_dialog_stylesheet(colors))
        self.result: str | None = None

        root = _page_layout(self)

        heading = QLineEdit(title)
        heading.setObjectName("titleInput")
        heading.setReadOnly(True)
        root.addWidget(heading)
        root.addSpacing(10)
        root.addWidget(_divider(colors))
        root.addSpacing(10)

        self.notes_edit = QPlainTextEdit(content)
        self.notes_edit.setPlaceholderText("Add notes...")
        _mute_placeholder(self.notes_edit, colors)
        root.addWidget(self.notes_edit, stretch=1)

        root.addSpacing(12)
        root.addLayout(_action_buttons(self, "Save", self._on_save))

        self.notes_edit.setFocus()

    def _on_save(self):
        self.result = self.notes_edit.toPlainText()
        self.accept()
