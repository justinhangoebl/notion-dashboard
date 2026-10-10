"""Custom dark title bar for QMainWindow.

DWM's caption-color attribute only works on Windows 11 (build 22000+), so on
Windows 10 there is no reliable way to recolor the native title bar. This
module replaces the native caption with a Qt-drawn one instead.

Move and resize are done through QWindow.startSystemMove()/
startSystemResize() (Qt 5.15+), the officially supported way to implement a
custom title bar on a frameless window. This avoids hand-rolled native
message handling (WM_NCHITTEST/WM_NCCALCSIZE via ctypes), which is easy to
get subtly wrong in a way that corrupts memory in the native event loop
instead of raising a catchable Python exception.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QIcon, QMouseEvent, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from notion_dashboard.ui import icons


RESIZE_MARGIN = 6  # px, hover distance from an edge that triggers a resize

_EDGE_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
}


class TitleBar(QWidget):
    """The dark, Qt-drawn replacement for the native window caption."""

    HEIGHT = 26

    ICON_REFRESH = icons.ICON_REFRESH
    ICON_SETTINGS = icons.ICON_SETTINGS
    ICON_MINIMIZE = icons.ICON_MINIMIZE
    ICON_MAXIMIZE = icons.ICON_MAXIMIZE
    ICON_RESTORE = icons.ICON_RESTORE
    ICON_CLOSE = icons.ICON_CLOSE

    refresh_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()
    close_clicked = pyqtSignal()

    ALL_BUTTONS = ("refresh", "settings", "minimize", "maximize", "close")

    def __init__(
        self,
        title: str,
        colors: dict,
        parent: QWidget | None = None,
        buttons: tuple[str, ...] = ALL_BUTTONS,
        icon: QIcon | None = None,
    ):
        super().__init__(parent)

        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("titleBar")

        self.setStyleSheet(
            f"""
            QWidget#titleBar {{
                background: {colors["bg"]};
                padding: 0;
                margin: 0;
            }}

            QLabel#titleText {{
                color: {colors["text"]};
                background: transparent;
                font-family: "Segoe UI";
                font-size: 9pt;
            }}

            QLabel#titleIcon {{
                background: transparent;
            }}

            QPushButton {{
                background: transparent;
                border: none;
                outline: none;
                padding: 0;
                margin: 0;
                color: {colors["text"]};
                font-family: "{icons.ICON_FONT}";
                font-size: 10pt;
            }}

            QPushButton:hover {{
                background: {colors["hover"]};
            }}

            QPushButton#closeButton:hover {{
                background: {colors["close_hover"]};
                color: white;
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        if icon is not None and not icon.isNull():
            icon_label = QLabel()
            icon_label.setObjectName("titleIcon")
            icon_label.setPixmap(icon.pixmap(16, 16))
            layout.addWidget(icon_label)
            layout.addSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleText")
        layout.addWidget(self.title_label, stretch=1)

        self.refresh_button: QPushButton | None = None
        self.settings_button: QPushButton | None = None
        self.minimize_button: QPushButton | None = None
        self.maximize_button: QPushButton | None = None
        self.close_button: QPushButton | None = None
        self._buttons: list[QPushButton] = []

        if "refresh" in buttons:
            self.refresh_button = self._make_button(self.ICON_REFRESH)
            self.refresh_button.clicked.connect(self.refresh_clicked)
            layout.addWidget(self.refresh_button)
            self._buttons.append(self.refresh_button)

        if "settings" in buttons:
            self.settings_button = self._make_button(self.ICON_SETTINGS)
            self.settings_button.clicked.connect(self.settings_clicked)
            layout.addWidget(self.settings_button)
            self._buttons.append(self.settings_button)

        if "minimize" in buttons:
            self.minimize_button = self._make_button(self.ICON_MINIMIZE)
            self.minimize_button.clicked.connect(self.minimize_clicked)
            layout.addWidget(self.minimize_button)
            self._buttons.append(self.minimize_button)

        if "maximize" in buttons:
            self.maximize_button = self._make_button(self.ICON_MAXIMIZE)
            self.maximize_button.clicked.connect(self.maximize_clicked)
            layout.addWidget(self.maximize_button)
            self._buttons.append(self.maximize_button)

        if "close" in buttons:
            self.close_button = self._make_button(self.ICON_CLOSE, object_name="closeButton")
            self.close_button.clicked.connect(self.close_clicked)
            layout.addWidget(self.close_button)
            self._buttons.append(self.close_button)

    def _make_button(self, text: str, object_name: str | None = None) -> QPushButton:
        button = QPushButton(text)
        if object_name:
            button.setObjectName(object_name)

        button.setFixedSize(44, self.HEIGHT)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def set_title(self, title: str):
        self.title_label.setText(title)

    def set_maximized(self, is_maximized: bool):
        if self.maximize_button is not None:
            self.maximize_button.setText(self.ICON_RESTORE if is_maximized else self.ICON_MAXIMIZE)

    def _over_a_button(self, pos: QPoint) -> bool:
        return any(button.geometry().contains(pos) for button in self._buttons)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and not self._over_a_button(
            event.position().toPoint()
        ):
            window = self.window().windowHandle()
            if window is not None:
                window.startSystemMove()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if (
            self.maximize_button is not None
            and event.button() == Qt.MouseButton.LeftButton
            and not self._over_a_button(event.position().toPoint())
        ):
            self.maximize_clicked.emit()
            event.accept()
            return

        super().mouseDoubleClickEvent(event)


class _ResizeHost(QWidget):
    """Container that fills the window and reserves a thin edge margin for
    resize hit-testing.

    QMainWindow's own mouse handlers never fire once a central widget
    covers the full client area, since Qt delivers mouse events to
    whichever child widget is under the cursor. Reserving an unoccupied
    margin here (same background color as everything else, so it reads
    as a normal thin border rather than a gap) gives us a widget that
    actually receives those edge events.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def _edge_at(self, pos: QPoint) -> Qt.Edge:
        rect = self.rect()
        edges = Qt.Edge(0)

        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= rect.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge

        if pos.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= rect.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge

        return edges

    def mousePressEvent(self, event: QMouseEvent):
        window = self.window()

        if event.button() == Qt.MouseButton.LeftButton and not window.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            window_handle = window.windowHandle()

            if edge and window_handle is not None:
                window_handle.startSystemResize(edge)
                event.accept()
                return

        super().mousePressEvent(event)


class FramelessWindow(QMainWindow):
    """QMainWindow with the native caption replaced by a Qt-drawn TitleBar.

    Subclasses build their content as usual via setCentralWidget(); this
    class wraps it together with the title bar automatically. Moving and
    resizing are handled by Qt's startSystemMove()/startSystemResize(), so
    OS behavior like Aero snap keeps working.
    """

    def __init__(self, colors: dict, parent: QWidget | None = None, icon: QIcon | None = None):
        super().__init__(parent)

        self._colors = colors
        self._content_host: _ResizeHost | None = None

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        if icon is not None:
            self.setWindowIcon(icon)

        self.title_bar = TitleBar(self.windowTitle(), colors, self, icon=icon)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_maximize)
        self.title_bar.close_clicked.connect(self.close)

        # Cursor updates for the resize margin are driven centrally from
        # here rather than from _ResizeHost's own mouse events: once the
        # pointer moves off _ResizeHost's exposed strip onto a child
        # widget stacked on top of it (the title bar, the scroll area,
        # any card...), _ResizeHost stops receiving move events for that
        # motion, so a cursor set on it would otherwise get stuck there
        # and leak into whatever child the pointer is now over. Watching
        # every mouse move application-wide sidesteps that entirely.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseMove and self._content_host is not None:
            self._update_resize_cursor(event.globalPosition().toPoint())

        return super().eventFilter(obj, event)

    def _update_resize_cursor(self, global_pos: QPoint):
        host = self._content_host

        if self.isMaximized():
            host.unsetCursor()
            return

        local = self.mapFromGlobal(global_pos)

        if not self.rect().contains(local):
            host.unsetCursor()
            return

        edge = host._edge_at(local)
        host.setCursor(
            QCursor(_EDGE_CURSORS[edge]) if edge in _EDGE_CURSORS else Qt.CursorShape.ArrowCursor
        )

    # ------------------------------------------------------------
    # Content wiring: subclasses still just call setCentralWidget()
    # ------------------------------------------------------------

    def setCentralWidget(self, widget: QWidget):
        host = _ResizeHost()
        outer = QVBoxLayout(host)
        outer.setContentsMargins(RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN)
        outer.setSpacing(0)
        outer.addWidget(self.title_bar)
        outer.addWidget(widget, stretch=1)

        self._content_host = host
        super().setCentralWidget(host)

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.set_title(title)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "title_bar") and event.type() == event.Type.WindowStateChange:
            self.title_bar.set_maximized(self.isMaximized())

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)


class FramelessDialog(QDialog):
    """QDialog with the native caption replaced by the same dark TitleBar
    used for the main window, so modals read as part of the same app
    instead of popping up with Windows' default light caption.

    Only a close button is shown - dialogs here are small and fixed-size,
    so minimize/maximize/refresh/settings don't apply. Subclasses build
    their form into `self.content_layout` instead of `self` directly.
    """

    def __init__(self, title: str, colors: dict, parent: QWidget | None = None):
        super().__init__(parent)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title_colors = dict(colors)
        title_colors["bg"] = colors.get("panel", colors["bg"])
        self.title_bar = TitleBar(title, title_colors, parent=self, buttons=("close",))
        self.title_bar.close_clicked.connect(self.reject)
        outer.addWidget(self.title_bar)

        content = QWidget()
        content.setObjectName("dialogContent")
        outer.addWidget(content, stretch=1)

        self.content_layout = QVBoxLayout(content)

    def showEvent(self, event):
        super().showEvent(event)

        # Qt's stylesheet polish (run on show) resets any QPalette role a
        # widget didn't get through QSS - such as PlaceholderText - back
        # to the style's default. Widgets muted via add_dialog._mute_
        # placeholder() stash their intended color as a dynamic property
        # so it can be reapplied here every time the dialog is shown.
        for widget in self.findChildren(QWidget):
            color_hex = widget.property("_placeholderColor")
            if color_hex:
                palette = widget.palette()
                palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(color_hex))
                widget.setPalette(palette)

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.set_title(title)
