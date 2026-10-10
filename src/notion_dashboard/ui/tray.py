"""System tray icon: the dashboard hides here when closed, so the app
keeps running in the background (e.g. for global hotkeys)."""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from notion_dashboard.ui.app_icon import app_icon
from notion_dashboard.ui.dashboard import Dashboard


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window: Dashboard, app: QApplication):
        super().__init__(app_icon(), app)

        self._window = window
        self._app = app

        self.setToolTip("Notion Dashboard")
        app.setWindowIcon(self.icon())

        menu = QMenu()
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {Dashboard.PANEL};
                color: {Dashboard.TEXT};
                border: 1px solid {Dashboard.BORDER};
                border-radius: 6px;
                padding: 4px;
                font-family: "Segoe UI";
                font-size: 9pt;
            }}
            QMenu::item {{
                padding: 6px 18px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background: {Dashboard.PANEL_HOVER};
            }}
            QMenu::separator {{
                height: 1px;
                background: {Dashboard.BORDER};
                margin: 4px 6px;
            }}
            """
        )

        show_action = QAction("Show dashboard", menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)

        refresh_action = QAction("Refresh", menu)
        refresh_action.triggered.connect(window.refresh)
        menu.addAction(refresh_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        # QSystemTrayIcon doesn't take ownership of the menu.
        self._menu = menu
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        window.notify.connect(self._on_notify)
        window.clock_notify.connect(self._on_clock_notify)

    def show_window(self):
        self._window.show_dashboard()

    def quit(self):
        self._window.quit_app()
        self.hide()
        self._app.quit()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._window.toggle_dashboard()

    def _on_notify(self, message: str, error: bool):
        # The dashboard shows these itself while it's visible.
        if self._window.isVisible():
            return
        icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
        self.showMessage("Notion Dashboard", message, icon, 4000)

    def _on_clock_notify(self, title: str, message: str):
        # Always shown: clocking in/out by hotkey happens from other apps.
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)
