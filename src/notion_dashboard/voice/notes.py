"""Voice notes: hotkey -> record -> live transcript overlay -> TODO.

The speech model runs in a separate process (voice/worker.py) so it never
slows the dashboard down. This module starts and talks to that process,
draws the recording overlay, and saves the result through the same
add-TODO path as the typed dialog.
"""

from __future__ import annotations

import ctypes
import html
import importlib.util
import json
import math
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QPointF, QProcess, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from notion_dashboard.hotkeys import GlobalHotkeys
from notion_dashboard.voice.cleanup import CLEANUP_DEFAULTS, CleanupError, clean_note, warm_up

WORKER = Path(__file__).resolve().parent / "worker.py"

VOICE_DEFAULTS = {
    "enabled": True,
    "model": "base",
    "device": "auto",
    "language": "auto",
    "silence_seconds": 2.0,
    **CLEANUP_DEFAULTS,
}

# The settings voice_worker.py is started with; changing any other voice
# setting doesn't need the speech model reloaded.
WORKER_KEYS = ("model", "device", "language", "silence_seconds", "test_audio_file")


def voice_config(config: dict) -> dict:
    return {**VOICE_DEFAULTS, **(config.get("voice") or {})}


def voice_installed() -> bool:
    """Checks for the optional packages without importing them (fast)."""
    return all(importlib.util.find_spec(name) for name in ("faster_whisper", "sounddevice"))


def split_note(text: str) -> tuple[str, str]:
    """(title, page content) for a dictated note.

    Short notes become the title alone; longer ones get their first
    sentence as the title and the full text as the page content.
    """

    text = " ".join(text.split())
    if len(text) <= 80:
        return text.rstrip("."), ""

    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if len(first) > 100:
        first = first[:80].rsplit(" ", 1)[0] + "…"
    return first.rstrip("."), text


def tidy_note(text: str, settings: dict, language: str = "") -> tuple[str, str, str]:
    """(title, page content, problem) for a dictated note.

    Runs the LLM cleanup if it's on; falls back to split_note() and
    reports why in `problem` if it fails.
    """

    if not settings.get("cleanup"):
        return *split_note(text), ""

    try:
        title, body = clean_note(text, settings, language)
    except CleanupError as exc:
        return *split_note(text), str(exc)

    raw = " ".join(text.split())
    if settings.get("keep_transcript") and len(raw) > 80:
        body = f"{body}\n\nOriginal dictation:\n{raw}".strip()
    return title, body, ""


# ==============================================================
# WORKER PROCESS
# ==============================================================


class VoiceWorkerProcess(QObject):
    """Runs voice_worker.py and turns its JSON lines into Qt signals."""

    # Not named `event`: that would shadow QObject.event(), which Qt calls
    # to deliver its own events.
    message = pyqtSignal(dict)
    exited = pyqtSignal()  # unexpectedly; it restarts itself
    crashed = pyqtSignal(str)  # gave up restarting

    MAX_RESTARTS = 3

    def __init__(self, settings: dict, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings
        self._process: QProcess | None = None
        self._buffer = b""
        self._shutting_down = False
        self._restarts: list[float] = []
        self.ready = False
        self.failed_message = ""

    def running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def start(self):
        if self.running():
            return

        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        s = self._settings

        process = QProcess(self)
        process.setStandardErrorFile(QProcess.nullDevice())
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._on_finished)
        arguments = [
            str(WORKER),
            "--model", str(s["model"]),
            "--device", str(s["device"]),
            "--language", str(s["language"]),
            "--silence", str(s["silence_seconds"]),
        ]
        if s.get("test_audio_file"):  # tests only: play a WAV instead of the mic
            arguments += ["--audio-file", str(s["test_audio_file"])]

        process.start(str(pythonw if pythonw.exists() else python), arguments)
        process.waitForStarted(3000)

        self._process = process
        self._buffer = b""
        self.ready = False
        self.failed_message = ""

    def send(self, command: str):
        if not self.running():
            self.start()
        self._process.write((json.dumps({"cmd": command}) + "\n").encode())

    def restart(self, settings: dict, start: bool):
        self.shutdown()
        self._settings = settings
        self._shutting_down = False
        self._restarts = []
        self.failed_message = ""
        if start:
            self.start()

    def shutdown(self):
        self._shutting_down = True
        if self.running():
            self._process.write(b'{"cmd": "quit"}\n')
            self._process.closeWriteChannel()
            if not self._process.waitForFinished(2000):
                self._process.kill()

    def _read(self):
        self._buffer += bytes(self._process.readAllStandardOutput())
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            try:
                event = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if event.get("event") == "ready":
                self.ready = True
            elif event.get("event") == "error" and not self.ready:
                self.failed_message = event.get("message", "")
            self.message.emit(event)

    def _on_finished(self):
        self.ready = False
        if self._shutting_down:
            return
        self.exited.emit()

        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < 60] + [now]
        if len(self._restarts) > self.MAX_RESTARTS:
            self.failed_message = self.failed_message or "The voice process keeps crashing."
            self.crashed.emit(self.failed_message)
            return
        QTimer.singleShot(2000, self.start)


# ==============================================================
# OVERLAY
# ==============================================================


class _Indicator(QWidget):
    """The round recording indicator. Its halo follows the mic level."""

    COLORS = {
        "rec": "#ff5a4f",
        "busy": "#f0b34a",
        "ok": "#4cc38a",
        "error": "#ff5a4f",
        "muted": "#6b6d74",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.mode = "rec"
        self._level = 0.0
        self._target = 0.0
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_level(self, value: float):
        self._target = max(0.0, min(1.0, value))

    def _tick(self):
        self._level += (self._target - self._level) * 0.35
        self._target *= 0.9
        self._phase = (self._phase + 0.08) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        color = QColor(self.COLORS.get(self.mode, "#ff5a4f"))

        if self.mode == "rec":
            breathing = 0.5 + 0.5 * math.sin(self._phase)
            halo = 8 + 8 * self._level + 2 * breathing
            glow = QColor(color)
            glow.setAlpha(int(60 + 80 * self._level))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, halo, halo)
            painter.setBrush(color)
            painter.drawEllipse(center, 7, 7)
        elif self.mode == "busy":
            pen = QPen(color, 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            start = int(-math.degrees(self._phase) * 16 * 2)
            painter.drawArc(QRectF(center.x() - 9, center.y() - 9, 18, 18), start, 270 * 16)
        elif self.mode == "ok":
            pen = QPen(color, 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline([QPointF(center.x() - 7, center.y()), QPointF(center.x() - 2, center.y() + 5), QPointF(center.x() + 8, center.y() - 5)])
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(center, 7, 7)


class _NoteInput(QLineEdit):
    """The overlay's text field; Esc is reported instead of ignored."""

    escaped = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(event)


class VoiceOverlay(QWidget):
    """Bottom-centre pill: indicator, live transcript, a text field to type
    the note instead, and a status line. Always on top. It takes keyboard
    focus while you dictate or type, and hands it back to the window you
    were in as soon as you're done."""

    WIDTH = 480
    TEXT_TAIL = 220
    PLACEHOLDER = "…or just start typing"

    typing_started = pyqtSignal()
    submitted = pyqtSignal(str)
    escaped = pyqtSignal()

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(self.WIDTH)
        self._previous_window = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 18, 12)
        layout.setSpacing(12)

        # The word-wrapping labels get their width up front: without it Qt
        # sizes them for a narrow width first and the pill comes out too tall.
        text_width = self.WIDTH - 16 - 18 - 34 - 12

        self.indicator = _Indicator()
        layout.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(3)

        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setFixedWidth(text_width)
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setStyleSheet('color: #ffffff; font: 10pt "Segoe UI"; background: transparent;')
        body.addWidget(self._text)

        self.input = _NoteInput()
        self.input.setFixedWidth(text_width)
        self.input.setPlaceholderText(self.PLACEHOLDER)
        self.input.setStyleSheet(
            'QLineEdit { color: #ffffff; font: 10pt "Segoe UI"; background: #0a0b0d;'
            " border: 1px solid #3d3e44; border-radius: 6px; padding: 4px 8px; }"
            " QLineEdit:focus { border: 1px solid #2383e2; }"
        )
        self.input.textEdited.connect(self._on_text_edited)
        self.input.returnPressed.connect(lambda: self.submitted.emit(self.input.text()))
        self.input.escaped.connect(self.escaped)
        self.input.hide()
        body.addWidget(self.input)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setFixedWidth(text_width)
        self._status.setStyleSheet('color: #9b9b9b; font: 8pt "Segoe UI"; background: transparent;')
        body.addWidget(self._status)

        layout.addLayout(body, stretch=1)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    # ---- states -------------------------------------------------------

    def listening(self, hint: str, loading: bool):
        self._hide_timer.stop()
        self.indicator.mode = "rec"
        self._text.show()
        self._set_text("", "Listening…")
        self.input.clear()
        self.input.show()
        self.hint(hint, loading)
        self._show()
        self._take_focus()

    def typing(self, hint: str):
        """Recording was dropped for the keyboard: only the field remains."""
        self.indicator.mode = "muted"
        self._text.hide()
        self._set_status(hint)

    def text(self) -> str:
        return self.input.text()

    def hint(self, text: str, loading: bool = False):
        self._set_status(("Loading voice model, keep talking  ·  " if loading else "") + text)
        self._reposition()

    def transcript(self, committed: str, pending: str):
        self._set_text(committed, pending)

    def level(self, value: float):
        self.indicator.set_level(value)

    def finishing(self, status: str = "Saving…"):
        self.indicator.mode = "busy"
        self._end_input()
        self._set_status(status)
        self._reposition()

    def done(self, title: str, problem: str = ""):
        self.indicator.mode = "ok"
        self._end_input()
        self._set_text(title, "")
        self._set_status(f"Added to TODOs without tidying up ({problem})" if problem else "Added to TODOs")
        self._hide_after(3500 if problem else 1800)

    def message(self, text: str, error: bool = False, hide_after: int = 1500):
        self.indicator.mode = "error" if error else "muted"
        self._end_input()
        self._set_text("", "")
        self._text.setText(f'<span style="color:{"#ff7369" if error else "#ffffff"}">{html.escape(text)}</span>')
        self._set_status("")
        self._show()
        self._hide_after(hide_after)

    # ---- helpers ------------------------------------------------------

    def _on_text_edited(self, text: str):
        if text:
            self.typing_started.emit()

    def _end_input(self):
        self.input.hide()
        self._text.show()
        self._give_back_focus()

    def _take_focus(self):
        """Focus the text field, remembering which window had focus. The
        hotkey press lets this process take the foreground. (On Linux the
        window manager hands focus back when the overlay hides.)"""
        if sys.platform == "win32":
            self._previous_window = ctypes.windll.user32.GetForegroundWindow()
        self.activateWindow()
        self.raise_()
        self.input.setFocus()

    def _give_back_focus(self):
        previous, self._previous_window = self._previous_window, 0
        if previous and self.isActiveWindow():
            ctypes.windll.user32.SetForegroundWindow(previous)

    def _set_text(self, committed: str, pending: str):
        committed, pending = committed.strip(), pending.strip()
        combined = f"{committed} {pending}".strip()
        if len(combined) > self.TEXT_TAIL:
            cut = len(combined) - self.TEXT_TAIL
            if cut < len(committed):
                committed = "…" + committed[cut:].split(" ", 1)[-1]
            else:
                committed, pending = "…", pending[cut - len(committed):]
        self._text.setText(
            f"{html.escape(committed)} "
            f'<span style="color:#8a8b91">{html.escape(pending)}</span>'
        )
        self._reposition()

    def _set_status(self, text: str):
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._reposition()

    def _show(self):
        self._reposition()
        self.show()
        self.raise_()

    def _hide_after(self, ms: int):
        self._hide_timer.start(ms)

    def _reposition(self):
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 28)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#3d3e44"), 1))
        painter.setBrush(QColor("#25262b"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)


# ==============================================================
# CONTROLLER
# ==============================================================


class VoiceNotes(QObject):
    """Hotkey press -> record -> save as TODO. One recording at a time."""

    saved = pyqtSignal(str, str)  # title, cleanup problem ("" if none)
    save_failed = pyqtSignal(str)

    ESC_NAME = "voice_cancel"
    START_DELAY_MS = 2000

    def __init__(
        self,
        settings: dict,
        hotkeys: GlobalHotkeys,
        save_callback: Callable[[dict], None],
        fallback: Callable[[], None],
        finish_hint: Callable[[], str],
        on_saved: Callable[[], None],
    ):
        super().__init__()
        self._settings = settings
        self._hotkeys = hotkeys
        self._save = save_callback
        self._fallback = fallback
        self._finish_hint = finish_hint
        self._on_saved = on_saved
        self._state = "idle"  # idle | recording | typing | finishing | saving

        self.available = bool(settings["enabled"]) and voice_installed()
        self.overlay = VoiceOverlay()
        self.worker = VoiceWorkerProcess(settings, self)
        self.worker.message.connect(self._on_event)
        self.worker.crashed.connect(lambda message: self._fail(f"Voice unavailable: {message}"))
        self.worker.exited.connect(lambda: self._fail("The voice process restarted, please try again"))
        self.saved.connect(self._on_saved_ok)
        self.save_failed.connect(self._on_save_failed)
        self.overlay.typing_started.connect(self._start_typing)
        self.overlay.submitted.connect(self._submit_typed)
        self.overlay.escaped.connect(self.cancel)

        if self.available:
            # Started after the dashboard is on screen, so launch stays fast.
            QTimer.singleShot(self.START_DELAY_MS, self.worker.start)

    # ---- entry points ---------------------------------------------------

    def toggle(self):
        if not self.available or self.worker.failed_message:
            self._fallback()
            return

        if self._state == "idle":
            self._state = "recording"
            self._hotkeys.add_temporary(self.ESC_NAME, "Esc")
            self.overlay.listening(self._hint(), loading=not self.worker.ready)
            self.worker.send("start")
            if self._settings.get("cleanup"):
                threading.Thread(target=warm_up, args=(self._settings,), daemon=True).start()
        elif self._state == "recording":
            self.worker.send("stop")
        elif self._state == "typing":
            self._submit_typed(self.overlay.text())

    def _hint(self) -> str:
        return f"{self._finish_hint()} or pause to finish  ·  Esc cancels"

    def cancel(self):
        if self._state == "recording":
            self.worker.send("cancel")
        elif self._state == "typing":
            self._end("Cancelled", hide_after=700)

    # ---- typing instead of dictating -------------------------------------

    def _start_typing(self):
        """A key was typed into the overlay: drop the recording, keep the
        field. The worker's "cancelled" reply is ignored in this state."""
        if self._state != "recording":
            return
        self._state = "typing"
        self.worker.send("cancel")
        # The temporary Esc hotkey would swallow Esc before the field sees it.
        self._hotkeys.remove(self.ESC_NAME)
        self.overlay.typing(f"Enter or {self._finish_hint()} saves  ·  Esc cancels")

    def _submit_typed(self, text: str):
        if self._state != "typing":
            return
        if not text.strip():
            self._end("Cancelled", hide_after=700)
            return

        self._state = "saving"
        self.overlay.finishing()
        title, content = split_note(text)

        def worker():
            try:
                self._save({"title": title, "due": None, "priority": "Low", "content": content})
                self.saved.emit(title, "")
            except Exception as exc:
                self.save_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def apply_settings(self, settings: dict):
        """Called after Settings is saved: restart the worker if needed."""
        if settings == self._settings:
            return
        if all(settings.get(k) == self._settings.get(k) for k in (*WORKER_KEYS, "enabled")):
            self._settings = settings  # only the cleanup changed
            return
        if self._state != "idle":
            self.worker.send("cancel")
            self._end("Voice settings changed", hide_after=700)
        self._settings = settings
        self.available = bool(settings["enabled"]) and voice_installed()
        self.worker.restart(settings, start=self.available)

    def shutdown(self):
        self._hotkeys.remove(self.ESC_NAME)
        self.worker.shutdown()
        self.overlay.hide()

    # ---- worker events --------------------------------------------------

    def _on_event(self, event: dict):
        name = event.get("event")

        if name == "error" and not self.worker.ready and self._state == "idle":
            return  # model failed to load; toggle() falls back from now on

        if self._state not in ("recording", "finishing"):
            return

        if name == "ready" and self._state == "recording":
            self.overlay.hint(self._hint())
        elif name == "level":
            self.overlay.level(event.get("value", 0.0))
        elif name == "partial":
            self.overlay.transcript(event.get("committed", ""), event.get("pending", ""))
        elif name == "finishing":
            self._state = "finishing"
            self._hotkeys.remove(self.ESC_NAME)
            self.overlay.finishing()
        elif name == "final":
            self._save_note(event.get("text", ""), event.get("language", ""))
        elif name == "no_speech":
            self._end("Didn't catch anything")
        elif name == "cancelled":
            self._end("Cancelled", hide_after=700)
        elif name == "error":
            self._end(event.get("message", "Voice error"), error=True)

    def _save_note(self, text: str, language: str):
        self._state = "saving"
        settings = self._settings
        if settings.get("cleanup"):
            self.overlay.finishing("Tidying up…")

        def worker():
            title, content, problem = tidy_note(text, settings, language)
            data = {"title": title, "due": None, "priority": "Low", "content": content}
            try:
                self._save(data)
                self.saved.emit(title, problem)
            except Exception as exc:
                self.save_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_saved_ok(self, title: str, problem: str):
        self._state = "idle"
        self.overlay.done(title, problem)
        self._on_saved()

    def _on_save_failed(self, message: str):
        self._end(f"Couldn't save to Notion: {message}", error=True)

    def _end(self, message: str, error: bool = False, hide_after: int = 1500):
        self._state = "idle"
        self._hotkeys.remove(self.ESC_NAME)
        self.overlay.message(message, error=error, hide_after=3500 if error else hide_after)

    def _fail(self, message: str):
        if self._state != "idle":
            self._end(message, error=True)
        self._state = "idle"
