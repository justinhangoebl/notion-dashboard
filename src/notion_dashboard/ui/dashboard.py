from __future__ import annotations

from datetime import date, datetime, timedelta
import html
import queue
import sys
import threading
import webbrowser
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from notion_dashboard.notion.api import Meeting, Todo, Workday
from notion_dashboard.ui.app_icon import app_icon
from notion_dashboard.ui.dialogs import AddMeetingDialog, AddTodoDialog, EditTodoDialog, make_pill
from notion_dashboard.ui.icons import (
    ICON_ADD,
    ICON_CALENDAR,
    ICON_EDIT,
    ICON_FONT,
    ICON_LOCATION,
    ICON_PREV as ICON_BACK,
    ICON_TODO,
    ICON_WORK,
    load_icon_font,
)
from notion_dashboard.ui.title_bar import FramelessWindow



# ==============================================================
# CLICKABLE CARD
# ==============================================================


class ClickableFrame(QFrame):
    """A card frame that opens its URL when double-clicked."""

    def __init__(self, url: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)

        self.url = url
        self.setObjectName("card")

        if url:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event):
        if self.url and event.button() == Qt.MouseButton.LeftButton:
            webbrowser.open(self.url)

        super().mouseDoubleClickEvent(event)


class TodoFrame(QFrame):
    """A list-row frame that marks the TODO done on click."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.setObjectName("todoCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

        super().mouseReleaseEvent(event)


class Snackbar(QWidget):
    """A floating, pill-shaped toast with an Undo action."""

    HEIGHT = 44
    DURATION_MS = 6000

    def __init__(
        self,
        colors: dict,
        parent: QWidget | None = None,
        position: Callable[[], None] | None = None,
    ):
        super().__init__(parent)

        self._position = position
        self.setObjectName("snackbar")
        # QWidget subclasses don't paint a stylesheet background/border
        # (the pill) without this.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self.HEIGHT)
        self._pending_undo: Callable[[], None] | None = None

        self.setStyleSheet(
            f"""
            QWidget#snackbar {{
                background: {colors["panel"]};
                border: 1px solid {colors["border"]};
                border-radius: {self.HEIGHT // 2}px;
            }}

            QLabel#snackbarText {{
                color: {colors["text"]};
                background: transparent;
                border: none;
                font-family: "Segoe UI";
                font-size: 9pt;
            }}

            QLabel#snackbarText[error="true"] {{
                color: {colors["warning"]};
            }}

            QPushButton#snackbarUndo {{
                background: transparent;
                border: none;
                color: {colors["accent"]};
                font-family: "Segoe UI";
                font-size: 9pt;
                font-weight: 600;
                padding: 0 16px 0 8px;
            }}

            QPushButton#snackbarUndo:hover {{
                color: {colors["text"]};
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 6, 0)
        layout.setSpacing(0)

        self.message_label = QLabel("")
        self.message_label.setObjectName("snackbarText")
        layout.addWidget(self.message_label, stretch=1)

        self.undo_button = QPushButton("UNDO")
        self.undo_button.setObjectName("snackbarUndo")
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_button.clicked.connect(self._on_undo)
        layout.addWidget(self.undo_button)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_message(self, text: str, undo: Callable[[], None] | None = None):
        self._display(text, error=False, undo=undo)

    def show_error(self, text: str):
        self._display(text, error=True, undo=None)

    def _display(self, text: str, error: bool, undo: Callable[[], None] | None):
        self.message_label.setProperty("error", "true" if error else "false")
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

        self.message_label.setText(text)
        self._pending_undo = undo
        self.undo_button.setVisible(undo is not None)
        self.adjustSize()
        # Positioned on every show, not just on resize: the first resize
        # happens before the window's layout has placed the widgets the
        # snackbar sits above, which put it off-screen.
        if self._position is not None:
            self._position()
        self.show()
        self.raise_()
        self._timer.start(self.DURATION_MS)

    def _on_undo(self):
        self._timer.stop()
        self.hide()

        if self._pending_undo is not None:
            pending, self._pending_undo = self._pending_undo, None
            pending()


# ==============================================================
# DASHBOARD
# ==============================================================


class Dashboard(FramelessWindow):

    BG = "#0a0b0d"
    PANEL = "#25262b"
    PANEL_HOVER = "#2f3037"
    TEXT = "#ffffff"
    MUTED = "#9b9b9b"
    ACCENT = "#2383e2"  # Notion blue
    BORDER = "#3d3e44"
    DIVIDER = "#3a3b41"
    ROW_HOVER = "#17181c"
    WARNING = "#e6b86a"
    TITLE_BAR_HOVER = "#35383E"
    CLOSE_HOVER = "#c0392b"

    SECTION_GAP = 22

    refresh_finished = pyqtSignal(list, list, list, object)
    action_error = pyqtSignal(str)
    action_done = pyqtSignal()
    todo_content_loaded = pyqtSignal(object, str)
    clock_failed = pyqtSignal(str)
    notify = pyqtSignal(str, bool)  # message, is_error
    # Clock in/out confirmations: shown as a Windows notification even
    # while the dashboard is visible (the hotkey works from anywhere).
    clock_notify = pyqtSignal(str, str)  # title, message

    def __init__(
        self,
        refresh_callback: Callable,
        complete_todo_callback: Callable[[str], None],
        undo_todo_callback: Callable[[str, str], None],
        settings_callback: Callable[["Dashboard"], None] | None = None,
        add_meeting_callback: Callable[[dict], None] | None = None,
        add_todo_callback: Callable[[dict], None] | None = None,
        get_todo_content_callback: Callable[[str], str] | None = None,
        set_todo_content_callback: Callable[[str, str], None] | None = None,
        clock_in_callback: Callable[[], None] | None = None,
        clock_out_callback: Callable[[Workday], None] | None = None,
        width: int = 520,
        height: int = 760,
    ):
        super().__init__(
            colors={
                "bg": self.BG,
                "text": self.TEXT,
                "muted": self.MUTED,
                "hover": self.TITLE_BAR_HOVER,
                "close_hover": self.CLOSE_HOVER,
            },
            icon=app_icon(),
        )

        self.refresh_callback = refresh_callback
        self.complete_todo_callback = complete_todo_callback
        self.undo_todo_callback = undo_todo_callback
        self.settings_callback = settings_callback
        self.add_meeting_callback = add_meeting_callback
        self.add_todo_callback = add_todo_callback
        self.get_todo_content_callback = get_todo_content_callback
        self.set_todo_content_callback = set_todo_content_callback
        self.clock_in_callback = clock_in_callback
        self.clock_out_callback = clock_out_callback
        self._clock_busy = False

        self._meetings: list[Meeting] = []
        self._todos: list[Todo] = []
        self._workdays: list[Workday] = []
        self._refresh_interval_ms = 300_000
        self._quitting = False
        self._add_todo_open = False
        self.close_to_tray = False

        self.setWindowTitle("Notion Dashboard")
        self.resize(width, height)
        self.setMinimumSize(400, 500)

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.setStyleSheet(self._build_stylesheet())

        self.refresh_finished.connect(self.render)
        self.action_done.connect(self.refresh)
        self.todo_content_loaded.connect(self._show_edit_todo_dialog)
        self.title_bar.refresh_clicked.connect(self.refresh)
        self.title_bar.settings_clicked.connect(self._open_settings)

        self._build()

        self.action_error.connect(self.snackbar.show_error)
        self.clock_failed.connect(self._on_clock_failed)
        self.notify.connect(self._on_notify)
        self.clock_notify.connect(lambda title, message: self._on_notify(f"{title}  ·  {message}", False))

        self.refresh()

    # ==========================================================
    # STYLESHEET
    #
    # All widget styling lives here, keyed by objectName, so cards
    # are built without allocating per-instance QFont/stylesheet
    # strings on every refresh.
    # ==========================================================

    def _build_stylesheet(self) -> str:
        return f"""
            QMainWindow, QWidget {{
                background: {self.BG};
                color: {self.TEXT};
                font-family: "Segoe UI";
            }}

            QScrollArea {{
                border: none;
                background: {self.BG};
            }}

            QScrollBar:vertical {{
                background: {self.BG};
                width: 8px;
                margin: 0px;
                border: none;
            }}

            QScrollBar::handle:vertical {{
                background: {self.BORDER};
                min-height: 30px;
                border-radius: 4px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {self.ACCENT};
            }}

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
                border: none;
            }}

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: transparent;
            }}

            QLabel#sectionIcon {{
                color: {self.TEXT};
                background: transparent;
                font-family: "{ICON_FONT}";
                font-size: 10pt;
            }}

            QLabel#sectionTitle {{
                color: {self.TEXT};
                background: transparent;
                font-family: "Segoe UI";
                font-size: 10pt;
                font-weight: 600;
            }}

            QLabel#sectionCount {{
                color: {self.MUTED};
                background: transparent;
                font-family: "Segoe UI";
                font-size: 9pt;
            }}

            QPushButton#addButton, QPushButton#notesButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
                color: {self.MUTED};
                font-family: "{ICON_FONT}";
                font-size: 9pt;
                padding: 0;
            }}

            QPushButton#addButton:hover, QPushButton#notesButton:hover {{
                background: {self.PANEL_HOVER};
                color: {self.TEXT};
            }}

            QFrame#rowDivider {{
                background: {self.DIVIDER};
                border: none;
            }}

            QFrame#card, QFrame#todoCard {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}

            QFrame#card:hover, QFrame#todoCard:hover {{
                background: {self.ROW_HOVER};
            }}

            QLabel#emptyText {{
                color: {self.MUTED};
                background: transparent;
                font: 9pt "Segoe UI";
                padding: 10px 8px;
            }}

            QLabel#rowTitle {{
                color: {self.TEXT};
                background: transparent;
                font: 10pt "Segoe UI";
            }}

            QLabel#rowMeta {{
                color: {self.MUTED};
                background: transparent;
                font: 8pt "Segoe UI";
            }}

            QLabel#rowHours {{
                color: {self.TEXT};
                background: transparent;
                font: 600 10pt "Segoe UI";
            }}

            QFrame#hoursBar {{
                background: transparent;
                border: none;
                border-top: 1px solid {self.DIVIDER};
            }}

            QFrame#hoursSeparator {{
                background: {self.DIVIDER};
                border: none;
                margin: 4px 0;
            }}

            QLabel#clockStatus {{
                color: {self.MUTED};
                background: transparent;
                font: 9pt "Segoe UI";
            }}

            QPushButton#clockButton {{
                background: {self.ACCENT};
                border: 1px solid {self.ACCENT};
                border-radius: 6px;
                color: white;
                font: 600 9pt "Segoe UI";
                padding: 5px 16px;
            }}

            QPushButton#clockButton:hover {{
                background: #3a93f0;
            }}

            QPushButton#clockButton[clockedIn="true"] {{
                background: transparent;
                border: 1px solid {self.BORDER};
                color: {self.TEXT};
            }}

            QPushButton#clockButton[clockedIn="true"]:hover {{
                background: {self.PANEL_HOVER};
            }}

            QPushButton#clockButton:disabled {{
                background: transparent;
                border: 1px solid {self.BORDER};
                color: {self.MUTED};
            }}

            QPushButton#hoursStat {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}

            QPushButton#hoursStat:hover {{
                background: {self.ROW_HOVER};
            }}

            QPushButton#hoursStat[active="true"] {{
                background: {self.PANEL};
            }}

            QLabel#hoursValue {{
                color: {self.TEXT};
                background: transparent;
                font: 600 14pt "Segoe UI";
            }}

            QLabel#hoursCaption {{
                color: {self.MUTED};
                background: transparent;
                font: 8pt "Segoe UI";
            }}

        """

    # ==========================================================
    # BUILD
    # ==========================================================

    def _build(self):

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 14, 10, 12)
        root.setSpacing(0)

        # Scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.scrollable = QWidget()
        self.scroll_layout = QVBoxLayout(self.scrollable)
        self.scroll_layout.setContentsMargins(0, 0, 4, 0)
        self.scroll_layout.setSpacing(0)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.scrollable)

        # Page 0: the main list. Page 1: workdays for the period picked in
        # the hours bar.
        self.stack = QStackedWidget()
        self.stack.addWidget(self.scroll_area)
        self.stack.addWidget(self._build_workday_page())
        root.addWidget(self.stack, stretch=1)

        # Working-hours bar, pinned below the list. Each stat is a button
        # that opens the workdays for its period.
        self.hours_bar = QFrame()
        self.hours_bar.setObjectName("hoursBar")
        bar_layout = QVBoxLayout(self.hours_bar)
        bar_layout.setContentsMargins(0, 8, 0, 0)
        bar_layout.setSpacing(6)

        # Clock in / out, above the totals. Hidden when workdays aren't
        # configured.
        clock_row = QWidget()
        clock_layout = QHBoxLayout(clock_row)
        clock_layout.setContentsMargins(8, 0, 4, 0)
        clock_layout.setSpacing(8)

        self._clock_status = QLabel()
        self._clock_status.setObjectName("clockStatus")
        clock_layout.addWidget(self._clock_status, stretch=1)

        self._clock_button = QPushButton()
        self._clock_button.setObjectName("clockButton")
        self._clock_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clock_button.clicked.connect(self.toggle_clock)
        clock_layout.addWidget(self._clock_button)

        clock_row.setVisible(self.clock_in_callback is not None and self.clock_out_callback is not None)
        bar_layout.addWidget(clock_row)

        bar = QHBoxLayout()
        bar.setSpacing(0)
        bar_layout.addLayout(bar)

        self._period: str | None = None
        self._hours_labels: dict[str, QLabel] = {}
        self._hours_buttons: dict[str, QPushButton] = {}
        for index, (key, caption) in enumerate(PERIODS):
            if index:
                separator = QFrame()
                separator.setObjectName("hoursSeparator")
                separator.setFixedWidth(1)
                bar.addWidget(separator)

            button = QPushButton()
            button.setObjectName("hoursStat")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(52)
            button.clicked.connect(lambda _=False, k=key: self._toggle_period(k))

            stat = QVBoxLayout(button)
            stat.setContentsMargins(0, 4, 0, 4)
            stat.setSpacing(0)
            value = QLabel("0h")
            value.setObjectName("hoursValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label = QLabel(caption)
            label.setObjectName("hoursCaption")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            stat.addWidget(value)
            stat.addWidget(label)

            bar.addWidget(button, stretch=1)
            self._hours_labels[key] = value
            self._hours_buttons[key] = button

        root.addWidget(self.hours_bar)

        # Keeps the running time and totals current while clocked in.
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(30_000)
        self._clock_timer.timeout.connect(self._update_hours)
        self._clock_timer.start()
        self._update_clock()

        # Undo toast, floating over the content above; positioned in
        # _position_snackbar() (called from resizeEvent).
        self.snackbar = Snackbar(
            colors={
                "panel": self.PANEL,
                "border": self.BORDER,
                "text": self.TEXT,
                "accent": self.ACCENT,
                "warning": self.WARNING,
            },
            parent=central,
            position=self._position_snackbar,
        )
        self.snackbar.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_snackbar()

    def closeEvent(self, event):
        # With a tray icon, the X button (and Alt+F4) hide to the tray so
        # the app keeps running; only quit_app() (tray menu -> Quit)
        # really closes.
        if self.close_to_tray and not self._quitting:
            event.ignore()
            self.hide()
            return

        super().closeEvent(event)

    def quit_app(self):
        self._quitting = True
        self.close()

    def _position_snackbar(self):
        central = self.snackbar.parentWidget()
        width = max(200, min(360, central.width() - 40))
        self.snackbar.setFixedWidth(width)
        x = (central.width() - width) // 2
        y = self.hours_bar.y() - self.snackbar.height() - 12
        self.snackbar.move(x, y)

    # ==========================================================
    # REFRESH
    # ==========================================================

    def _open_settings(self):
        if self.settings_callback is not None:
            self.settings_callback(self)

    def _dialog_colors(self) -> dict:
        return {
            "bg": self.BG,
            "panel": self.PANEL,
            "text": self.TEXT,
            "muted": self.MUTED,
            "border": self.BORDER,
            "accent": self.ACCENT,
            "accent_hover": "#3a93f0",
            "hover": self.PANEL_HOVER,
            "close_hover": self.CLOSE_HOVER,
        }

    def _add_meeting_clicked(self):
        if self.add_meeting_callback is None:
            return

        dialog = AddMeetingDialog(self._dialog_colors(), parent=self)
        if dialog.exec() and dialog.result is not None:
            data = dialog.result
            self._run_creation(lambda: self.add_meeting_callback(data))

    def add_todo(self):
        if self.add_todo_callback is None or self._add_todo_open:
            return

        dialog = AddTodoDialog(self._dialog_colors(), parent=self)
        # Opened by a global hotkey, the dashboard may be hidden in the
        # tray or behind other windows: keep the dialog on top and focused.
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        QTimer.singleShot(0, lambda: (dialog.raise_(), dialog.activateWindow()))

        self._add_todo_open = True
        try:
            accepted = dialog.exec()
        finally:
            self._add_todo_open = False

        if accepted and dialog.result is not None:
            data = dialog.result
            self._run_creation(lambda: self.add_todo_callback(data))

    def show_dashboard(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_dashboard(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_dashboard()

    def _run_creation(self, fn: Callable[[], None]):
        def worker():
            try:
                fn()
                self.action_done.emit()
            except Exception as exc:
                self.action_error.emit(f"Couldn't add: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _open_todo_notes(self, todo: Todo):
        if self.get_todo_content_callback is None:
            return

        def worker():
            try:
                content = self.get_todo_content_callback(todo.id)
                self.todo_content_loaded.emit(todo, content)
            except Exception as exc:
                self.action_error.emit(f"Couldn't load notes: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _show_edit_todo_dialog(self, todo: Todo, content: str):
        dialog = EditTodoDialog(todo.title, content, self._dialog_colors(), parent=self)
        if dialog.exec() and dialog.result is not None and self.set_todo_content_callback is not None:
            new_content = dialog.result

            def worker():
                try:
                    self.set_todo_content_callback(todo.id, new_content)
                except Exception as exc:
                    self.action_error.emit(f"Couldn't save notes: {exc}")

            threading.Thread(target=worker, daemon=True).start()

    def apply_app_settings(self, app_config: dict):
        """Apply app-level settings that can change without a restart."""

        self._refresh_interval_ms = int(app_config.get("refresh_minutes", 5)) * 60_000
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.start(self._refresh_interval_ms)

    def refresh(self):
        def worker():
            try:
                meetings, todos, workdays, error = self.refresh_callback()
                self.refresh_finished.emit(meetings, todos, workdays, error)
            except Exception as exc:
                self.refresh_finished.emit([], [], [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _run_background(self, fn: Callable[[], None]):
        # Status writes (complete / undo) go through a single serial queue
        # rather than each getting its own thread: two independent threads
        # give no guarantee which request reaches Notion first, so a quick
        # complete-then-undo could race and leave the wrong status saved.
        # A FIFO queue with one worker preserves the order they were
        # issued in.
        if not hasattr(self, "_task_queue"):
            self._task_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
            threading.Thread(target=self._task_worker, daemon=True).start()

        self._task_queue.put(fn)

    def _task_worker(self):
        while True:
            fn = self._task_queue.get()
            try:
                fn()
            except Exception as exc:
                print(f"Notion update failed: {exc}")

    # ==========================================================
    # RENDER
    # ==========================================================

    def render(
        self,
        meetings: list[Meeting],
        todos: list[Todo],
        workdays: list[Workday],
        error: str | None,
    ):
        today_str = date.today().strftime("%A, %d %B %Y")
        self.setWindowTitle(f"Notion Dashboard - {today_str}")

        if error:
            self.snackbar.show_error(f"Notion error: {error}")

        self._meetings = meetings
        self._todos = todos
        self._workdays = workdays
        self._clock_busy = False
        self._render_lists()
        self._update_hours()

        # Five minute refresh
        if not hasattr(self, "_refresh_timer"):
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setSingleShot(True)
            self._refresh_timer.timeout.connect(self.refresh)

        self._refresh_timer.start(self._refresh_interval_ms)

    def _render_lists(self):
        self.clear()

        self.section(
            ICON_CALENDAR,
            "Upcoming",
            len(self._meetings),
            on_add=self._add_meeting_clicked if self.add_meeting_callback else None,
        )
        if self._meetings:
            for index, meeting in enumerate(self._meetings):
                if index:
                    self.divider()
                self.meeting_row(meeting)
        else:
            self.empty("No meetings in the next week")

        self.section(
            ICON_TODO,
            "TODOs",
            len(self._todos),
            on_add=self.add_todo if self.add_todo_callback else None,
        )
        if self._todos:
            for index, todo in enumerate(self._todos):
                if index:
                    self.divider()
                self.todo_row(todo)
        else:
            self.empty("No open TODOs")

    def _update_hours(self):
        totals = summarize_hours(self._workdays, datetime.now().astimezone())
        for key, label in self._hours_labels.items():
            label.setText(format_hours(totals[key]))

        self._update_clock()
        if self._period is not None:
            self._render_workdays()

    # ==========================================================
    # CLOCK IN / OUT
    # ==========================================================

    def _open_workday(self) -> Workday | None:
        return next((w for w in self._workdays if w.is_open), None)

    def _update_clock(self):
        open_day = self._open_workday()
        button = self._clock_button

        if open_day is not None:
            elapsed = format_hours(open_day.hours_at(datetime.now().astimezone()))
            self._clock_status.setText(f"Clocked in since {open_day.start:%H:%M}  ·  {elapsed}")
            button.setText("Clock out")
        else:
            self._clock_status.setText("Not clocked in")
            button.setText("Clock in")

        button.setProperty("clockedIn", open_day is not None)
        button.setEnabled(not self._clock_busy)
        if self._clock_busy:
            button.setText("Saving…")
        button.style().unpolish(button)
        button.style().polish(button)

    def toggle_clock(self):
        if self._clock_busy or self.clock_in_callback is None or self.clock_out_callback is None:
            return

        now = datetime.now().astimezone()
        open_day = self._open_workday()
        if open_day is None:
            action = self.clock_in_callback
            title, message = "Clocked in", f"Started at {now:%H:%M}"
        else:
            action = lambda: self.clock_out_callback(open_day)
            worked = open_day.hours_at(now)
            title = "Clocked out"
            message = f"Worked {format_hours(worked)} ({open_day.start:%H:%M}–{now:%H:%M})"
            today = summarize_hours(self._workdays, now)["today"]
            if today - worked >= 1 / 60:  # several sessions today
                message += f"  ·  {format_hours(today)} today"

        self._clock_busy = True
        self._update_clock()

        def worker():
            try:
                action()
                self.action_done.emit()
                self.clock_notify.emit(title, message)
            except Exception as exc:
                self.clock_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_clock_failed(self, message: str):
        self._clock_busy = False
        self._update_clock()
        self.notify.emit(f"Couldn't update clock: {message}", True)

    def _on_notify(self, message: str, error: bool):
        # When hidden in the tray, TrayIcon shows these as notifications.
        if not self.isVisible():
            return
        if error:
            self.snackbar.show_error(message)
        else:
            self.snackbar.show_message(message)

    # ==========================================================
    # WORKDAYS PAGE
    # ==========================================================

    def _build_workday_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 4, 0)
        header.setSpacing(6)

        back = QPushButton(ICON_BACK)
        back.setObjectName("addButton")
        back.setFixedSize(26, 26)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self._toggle_period(None))
        header.addWidget(back)

        icon = QLabel(ICON_WORK)
        icon.setObjectName("sectionIcon")
        header.addWidget(icon)

        self._workday_title = QLabel()
        self._workday_title.setObjectName("sectionTitle")
        header.addWidget(self._workday_title)

        self._workday_count = QLabel()
        self._workday_count.setObjectName("sectionCount")
        header.addWidget(self._workday_count)

        header.addStretch(1)

        self._workday_total = QLabel()
        self._workday_total.setObjectName("rowHours")
        header.addWidget(self._workday_total)

        layout.addLayout(header)
        layout.addSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        self.workday_layout = QVBoxLayout(content)
        self.workday_layout.setContentsMargins(0, 0, 4, 0)
        self.workday_layout.setSpacing(0)
        self.workday_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        return page

    def _toggle_period(self, period: str | None):
        if period == self._period:
            period = None
        self._period = period

        for key, button in self._hours_buttons.items():
            button.setProperty("active", key == period)
            button.style().unpolish(button)
            button.style().polish(button)

        if period is None:
            self.stack.setCurrentIndex(0)
        else:
            self._render_workdays()
            self.stack.setCurrentIndex(1)

    def _render_workdays(self):
        layout = self.workday_layout
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        workdays = workdays_in_period(self._workdays, self._period, date.today())
        caption = dict(PERIODS)[self._period]
        if self._period == "month":
            caption = date.today().strftime("%B %Y")

        self._workday_title.setText(caption)
        self._workday_count.setText(str(len(workdays)))
        now = datetime.now().astimezone()
        self._workday_total.setText(format_hours(sum(w.hours_at(now) for w in workdays)))

        self.divider(layout)
        if not workdays:
            self.empty("No workdays logged", layout)
        for index, workday in enumerate(workdays):
            if index:
                self.divider(layout)
            self.workday_row(workday, layout)

    # ==========================================================
    # CLEAR
    # ==========================================================

    def clear(self):
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    # ==========================================================
    # SECTION HEADER / DIVIDER / EMPTY
    # ==========================================================

    def section(
        self,
        icon: str,
        title: str,
        count: int,
        on_add: Callable[[], None] | None = None,
    ):
        if self.scroll_layout.count() > 0:
            self.scroll_layout.addSpacing(self.SECTION_GAP)

        # A real widget (not a nested layout) so clear() can delete it.
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 0, 0, 0)
        row.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setObjectName("sectionIcon")
        row.addWidget(icon_label)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        row.addWidget(title_label)

        count_label = QLabel(str(count))
        count_label.setObjectName("sectionCount")
        row.addWidget(count_label)

        row.addStretch(1)

        if on_add is not None:
            add_button = QPushButton(ICON_ADD)
            add_button.setObjectName("addButton")
            add_button.setFixedSize(26, 26)
            add_button.setCursor(Qt.CursorShape.PointingHandCursor)
            add_button.clicked.connect(on_add)
            row.addWidget(add_button)

        self.scroll_layout.addWidget(header)
        self.scroll_layout.addSpacing(6)
        self.divider()

    def divider(self, layout: QVBoxLayout | None = None):
        line = QFrame()
        line.setObjectName("rowDivider")
        line.setFixedHeight(1)
        # Not `layout or ...`: an empty QLayout has len() 0 and is falsy.
        (layout if layout is not None else self.scroll_layout).addWidget(line)

    def empty(self, text: str, layout: QVBoxLayout | None = None):
        label = QLabel(text)
        label.setObjectName("emptyText")
        (layout if layout is not None else self.scroll_layout).addWidget(label)

    # ==========================================================
    # MEETING ROW
    # ==========================================================

    def meeting_row(self, meeting: Meeting):
        frame = ClickableFrame(meeting.link or meeting.url)

        body = QVBoxLayout(frame)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(3)

        title = QLabel(meeting.title)
        title.setObjectName("rowTitle")
        title.setWordWrap(True)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(title)

        details = []
        if meeting.start is not None:
            details.append(html.escape(format_day(meeting.start)))
        details.append(html.escape(format_time_range(meeting.start, meeting.end)))
        if meeting.location:
            details.append(
                f"<span style=\"font-family:'{ICON_FONT}'; font-size:7pt;\">{ICON_LOCATION}</span>"
                f"&nbsp;{html.escape(meeting.location)}"
            )

        meta = QLabel(" &nbsp;·&nbsp; ".join(details))
        meta.setObjectName("rowMeta")
        meta.setTextFormat(Qt.TextFormat.RichText)
        meta.setWordWrap(True)
        meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(meta)

        self.scroll_layout.addWidget(frame)

    # ==========================================================
    # TODO ROW
    # ==========================================================

    def todo_row(self, todo: Todo):
        frame = TodoFrame()
        frame.clicked.connect(lambda: self._complete_todo(todo))

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 8, 6, 8)
        layout.setSpacing(6)

        body = QVBoxLayout()
        body.setSpacing(4)

        title = QLabel(todo.title)
        title.setObjectName("rowTitle")
        title.setWordWrap(True)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(8)

        if todo.priority:
            meta.addWidget(make_pill(todo.priority, self._dialog_colors()))

        for text in (f"Due {format_date(todo.due)}" if todo.due else "", todo.status):
            if text:
                label = QLabel(text)
                label.setObjectName("rowMeta")
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                meta.addWidget(label)

        meta.addStretch(1)
        body.addLayout(meta)

        layout.addLayout(body, stretch=1)

        if self.get_todo_content_callback is not None:
            notes_button = QPushButton(ICON_EDIT)
            notes_button.setObjectName("notesButton")
            notes_button.setFixedSize(26, 26)
            notes_button.setCursor(Qt.CursorShape.PointingHandCursor)
            notes_button.clicked.connect(lambda checked=False, t=todo: self._open_todo_notes(t))
            layout.addWidget(notes_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.scroll_layout.addWidget(frame)

    # ==========================================================
    # WORKDAY ROW
    # ==========================================================

    def workday_row(self, workday: Workday, layout: QVBoxLayout):
        frame = ClickableFrame(workday.url)

        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(8)

        body = QVBoxLayout()
        body.setSpacing(3)

        heading = format_day(workday.start) if workday.start is not None else "No date"
        if workday.title and workday.title.casefold() != "workday":
            heading = f"{heading}  ·  {workday.title}"

        title = QLabel(heading)
        title.setObjectName("rowTitle")
        title.setWordWrap(True)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(title)

        if workday.is_open:
            time_range = f"{workday.start:%H:%M} – now"
        else:
            time_range = format_time_range(workday.start, workday.end)
        meta = QLabel(time_range)
        meta.setObjectName("rowMeta")
        meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(meta)

        row.addLayout(body, stretch=1)

        hours = QLabel(format_hours(workday.hours_at(datetime.now().astimezone())))
        hours.setObjectName("rowHours")
        hours.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(hours, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(frame)

    # ==========================================================
    # TODO COMPLETE / UNDO
    # ==========================================================

    def _complete_todo(self, todo: Todo):
        if todo not in self._todos:
            return

        index = self._todos.index(todo)
        self._todos.remove(todo)
        self._render_lists()

        self.snackbar.show_message(
            f"Marked done: {todo.title}",
            undo=lambda: self._undo_todo(todo, index),
        )

        self._run_background(lambda: self.complete_todo_callback(todo.id))

    def _undo_todo(self, todo: Todo, index: int):
        self._todos.insert(min(index, len(self._todos)), todo)
        self._render_lists()

        self._run_background(lambda: self.undo_todo_callback(todo.id, todo.status))


# ==============================================================
# FORMATTERS
# ==============================================================


def format_time_range(
    start: datetime | date | None,
    end: datetime | date | None,
) -> str:
    if not isinstance(start, datetime):
        return "All day"

    left = start.strftime("%H:%M")
    if isinstance(end, datetime):
        return f"{left} – {end.strftime('%H:%M')}"

    return left


def format_date(value: datetime | date) -> str:
    return value.strftime("%d %b")


def format_hours(hours: float) -> str:
    total_minutes = int(round(hours * 60))
    whole, minutes = divmod(total_minutes, 60)
    return f"{whole}h {minutes:02d}m" if minutes else f"{whole}h"


PERIODS = (("today", "Today"), ("week", "This week"), ("month", "This month"))


def workdays_in_period(workdays: list[Workday], period: str, today: date) -> list[Workday]:
    """Workdays for today, this week (Mon-Sun) or this calendar month.
    Workdays after today are planned, not worked, so they're left out."""

    week_start = today - timedelta(days=today.weekday())
    result = []

    for workday in workdays:
        if workday.start is None:
            continue
        day = workday.start.date() if isinstance(workday.start, datetime) else workday.start
        if day > today:
            continue
        if (
            (period == "today" and day == today)
            or (period == "week" and day >= week_start)
            or (period == "month" and (day.year, day.month) == (today.year, today.month))
        ):
            result.append(workday)

    return result


def summarize_hours(workdays: list[Workday], now: datetime) -> dict[str, float]:
    """Totals per period; a workday you're clocked into counts up to `now`."""
    return {
        period: sum(w.hours_at(now) for w in workdays_in_period(workdays, period, now.date()))
        for period, _ in PERIODS
    }


def format_day(value: datetime | date) -> str:
    day = value.date() if isinstance(value, datetime) else value
    delta = (day - date.today()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return day.strftime("%a %d %b")


# ==============================================================
# STANDALONE TEST
# ==============================================================


if __name__ == "__main__":

    qt_app = QApplication(sys.argv)
    load_icon_font()

    def example_refresh():
        return [], [], [], None

    def example_complete(page_id: str):
        print(f"complete {page_id}")

    def example_undo(page_id: str, previous_status: str):
        print(f"undo {page_id} -> {previous_status}")

    def example_add_meeting(data: dict):
        print(f"add meeting {data}")

    def example_add_todo(data: dict):
        print(f"add todo {data}")

    def example_get_todo_content(page_id: str) -> str:
        return f"Notes for {page_id}"

    def example_set_todo_content(page_id: str, content: str):
        print(f"set content {page_id} -> {content!r}")

    window = Dashboard(
        refresh_callback=example_refresh,
        complete_todo_callback=example_complete,
        undo_todo_callback=example_undo,
        add_meeting_callback=example_add_meeting,
        add_todo_callback=example_add_todo,
        get_todo_content_callback=example_get_todo_content,
        set_todo_content_callback=example_set_todo_content,
    )
    window.show()

    sys.exit(qt_app.exec())
