from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import webbrowser

import yaml
from dotenv import load_dotenv, set_key
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from app_icon import app_icon
from hotkeys import GlobalHotkeys, hotkeys_from_config
from notion_api import NotionRepository, Workday
from overlay import Dashboard
from settings_dialog import SettingsDialog
from setup_wizard import SetupWizard
from tray import TrayIcon
from voice_notes import VoiceNotes, voice_config


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict):
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def saved_token() -> str:
    load_dotenv(ENV_PATH)
    return os.getenv("NOTION_TOKEN", "").strip()


def load_token() -> str:
    token = saved_token()

    if not token:
        raise RuntimeError(
            "NOTION_TOKEN is missing. "
            "Run main.py --setup or create a .env file."
        )

    return token


def save_token(token: str):
    set_key(str(ENV_PATH), "NOTION_TOKEN", token)
    os.environ["NOTION_TOKEN"] = token


def needs_setup(config: dict) -> bool:
    notion = config.get("notion") or {}
    return not (
        saved_token()
        and notion.get("calendar_data_source_id")
        and notion.get("todo_data_source_id")
        and config.get("calendar")
        and config.get("todo")
        and config.get("app")
    )


def run_setup(config: dict) -> dict | None:
    """Shows the setup window; saves and returns the new config, or None
    if the user cancelled."""

    wizard = SetupWizard(config, dialog_colors(), token=saved_token())
    if not wizard.exec() or wizard.result_config is None:
        return None

    save_token(wizard.result_token)
    save_config(wizard.result_config)
    return wizard.result_config


def dialog_colors() -> dict:
    return {
        "bg": Dashboard.BG,
        "panel": Dashboard.PANEL,
        "text": Dashboard.TEXT,
        "muted": Dashboard.MUTED,
        "border": Dashboard.BORDER,
        "accent": Dashboard.ACCENT,
        "accent_hover": "#3a93f0",
        "hover": Dashboard.PANEL_HOVER,
        "close_hover": Dashboard.CLOSE_HOVER,
    }


def make_notion_actions(config: dict):
    """Build the fetch/complete/undo callbacks the dashboard needs.

    A single NotionRepository (and Notion client) is shared across all
    three so a background fetch and a background status update never
    race each other over separate connections.
    """

    repo = NotionRepository(
        load_token()
    )

    notion_cfg = config["notion"]
    calendar_cfg = config["calendar"]
    todo_cfg = config["todo"]

    status_property = todo_cfg["status_property"]
    completed_statuses = todo_cfg.get("completed_statuses", [])
    done_status = completed_statuses[0] if completed_statuses else "Done"

    def fetch():
        meetings = repo.get_meetings(
            data_source_id=notion_cfg[
                "calendar_data_source_id"
            ],
            title_property=calendar_cfg[
                "title_property"
            ],
            date_property=calendar_cfg[
                "date_property"
            ],
            location_property=calendar_cfg[
                "location_property"
            ],
            description_property=calendar_cfg[
                "description_property"
            ],
            link_property=calendar_cfg.get(
                "link_property",
                "",
            ),
            tags_property=calendar_cfg.get("tags_property", ""),
            exclude_tag=calendar_cfg.get("workday_tag", ""),
        )

        workdays = []
        if calendar_cfg.get("tags_property") and calendar_cfg.get("workday_tag"):
            workdays = repo.get_workdays(
                data_source_id=notion_cfg["calendar_data_source_id"],
                tags_property=calendar_cfg["tags_property"],
                workday_tag=calendar_cfg["workday_tag"],
                start_property=calendar_cfg["date_property"],
                end_property=calendar_cfg.get("end_property", ""),
                hours_property=calendar_cfg.get("hours_property", ""),
            )

        todos = repo.get_todos(
            data_source_id=notion_cfg[
                "todo_data_source_id"
            ],
            title_property=todo_cfg[
                "title_property"
            ],
            due_property=todo_cfg[
                "due_property"
            ],
            status_property=status_property,
            priority_property=todo_cfg.get(
                "priority_property",
                "",
            ),
            completed_statuses=completed_statuses,
        )

        max_meetings = config["app"].get(
            "max_meetings",
            10,
        )

        max_todos = config["app"].get(
            "max_todos",
            12,
        )

        return (
            meetings[:max_meetings],
            todos[:max_todos],
            workdays,
            None,
        )

    def complete_todo(page_id: str) -> None:
        repo.set_todo_status(page_id, status_property, done_status)

    def undo_todo(page_id: str, previous_status: str) -> None:
        repo.set_todo_status(page_id, status_property, previous_status)

    def add_meeting(data: dict) -> None:
        repo.create_meeting(
            data_source_id=notion_cfg["calendar_data_source_id"],
            title_property=calendar_cfg["title_property"],
            date_property=calendar_cfg["date_property"],
            location_property=calendar_cfg["location_property"],
            title=data["title"],
            start=data["start"],
            end=data.get("end"),
            location=data.get("location", ""),
            link_property=calendar_cfg.get("link_property", ""),
            link=data.get("link", ""),
        )

    def add_todo(data: dict) -> None:
        todo = repo.create_todo(
            data_source_id=notion_cfg["todo_data_source_id"],
            title_property=todo_cfg["title_property"],
            due_property=todo_cfg["due_property"],
            priority_property=todo_cfg.get("priority_property", ""),
            title=data["title"],
            due=data.get("due"),
            priority=data.get("priority", ""),
        )

        content = data.get("content", "")
        if content:
            repo.set_page_content(todo.id, content)

    def get_todo_content(page_id: str) -> str:
        return repo.get_page_content(page_id)

    def set_todo_content(page_id: str, content: str) -> None:
        repo.set_page_content(page_id, content)

    def now_to_minute() -> datetime:
        return datetime.now().astimezone().replace(second=0, microsecond=0)

    def clock_in() -> None:
        repo.clock_in(
            data_source_id=notion_cfg["calendar_data_source_id"],
            tags_property=calendar_cfg["tags_property"],
            workday_tag=calendar_cfg["workday_tag"],
            start_property=calendar_cfg["date_property"],
            when=now_to_minute(),
        )

    def clock_out(workday: Workday) -> None:
        repo.clock_out(
            workday,
            start_property=calendar_cfg["date_property"],
            end_property=calendar_cfg.get("end_property", ""),
            when=now_to_minute(),
        )

    workdays_enabled = bool(calendar_cfg.get("tags_property") and calendar_cfg.get("workday_tag"))

    return SimpleNamespace(
        fetch=fetch,
        complete_todo=complete_todo,
        undo_todo=undo_todo,
        add_meeting=add_meeting,
        add_todo=add_todo,
        get_todo_content=get_todo_content,
        set_todo_content=set_todo_content,
        clock_in=clock_in if workdays_enabled else None,
        clock_out=clock_out if workdays_enabled else None,
    )


INSTANCE_SERVER = "PhDProductivity.NotionDashboard"


def show_running_instance() -> bool:
    """If the dashboard is already running, ask it to show itself.

    A second copy couldn't register the hotkeys (the first one owns them),
    so it would look like the hotkeys silently stopped working.
    """

    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def listen_for_second_launch(window: Dashboard) -> QLocalServer:
    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_SERVER)  # stale name after a crash
    server.listen(INSTANCE_SERVER)
    server.newConnection.connect(window.show_dashboard)
    return server


def apply_hotkeys(hotkeys: GlobalHotkeys, config: dict, window: Dashboard):
    problems = hotkeys.apply(hotkeys_from_config(config))
    if problems:
        window.snackbar.show_error("Hotkey not set - " + "; ".join(problems))


def make_open_settings(config: dict, hotkeys: GlobalHotkeys, on_saved: list):
    def open_settings(window: Dashboard):
        colors = dialog_colors()

        # Registered hotkeys are swallowed system-wide, so the hotkey
        # fields couldn't record the current combinations. Suspend them
        # while Settings is open.
        hotkeys.unregister_all()
        try:
            dialog = SettingsDialog(config, colors, parent=window)
            if dialog.exec() and dialog.result_config is not None:
                config.clear()
                config.update(dialog.result_config)
                save_config(config)
                window.apply_app_settings(config["app"])
                for listener in on_saved:
                    listener(config)
        finally:
            apply_hotkeys(hotkeys, config, window)

    return open_settings


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the configured PhD Notion page.",
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Show the Notion setup window (token, workspace) again.",
    )

    args = parser.parse_args()

    # --------------------------------------------------------------
    # Qt application
    # --------------------------------------------------------------

    # Without its own AppUserModelID, a pythonw.exe process is grouped under
    # Python in the taskbar and shows the Python icon instead of ours.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PhDProductivity.NotionDashboard"
        )

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Notion Dashboard")
    qt_app.setWindowIcon(app_icon())

    # Launched again while running: bring the running dashboard forward.
    if show_running_instance():
        return

    # --------------------------------------------------------------
    # First start: token and Notion workspace
    # --------------------------------------------------------------

    config = load_config()

    if args.setup or needs_setup(config):
        config = run_setup(config)
        if config is None:
            return

    # --------------------------------------------------------------
    # Open Notion page
    # --------------------------------------------------------------

    if (
        config["app"].get(
            "open_notion_on_start",
            True,
        )
        and not args.no_open
        and config["notion"].get(
            "phd_page_url"
        )
    ):
        webbrowser.open(
            config["notion"]["phd_page_url"]
        )

    notion = make_notion_actions(config)

    hotkeys = GlobalHotkeys(qt_app)
    settings_listeners: list = []

    window = Dashboard(
        refresh_callback=notion.fetch,
        complete_todo_callback=notion.complete_todo,
        undo_todo_callback=notion.undo_todo,
        settings_callback=make_open_settings(config, hotkeys, settings_listeners),
        add_meeting_callback=notion.add_meeting,
        add_todo_callback=notion.add_todo,
        get_todo_content_callback=notion.get_todo_content,
        set_todo_content_callback=notion.set_todo_content,
        clock_in_callback=notion.clock_in,
        clock_out_callback=notion.clock_out,
        width=config["app"].get(
            "window_width",
            520,
        ),
        height=config["app"].get(
            "window_height",
            760,
        ),
    )

    window.apply_app_settings(config["app"])
    instance_server = listen_for_second_launch(window)  # kept alive for the app's lifetime

    # Keep the tray icon referenced for the app's lifetime.
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(window, qt_app)
        tray.show()
        window.close_to_tray = True
        qt_app.setQuitOnLastWindowClosed(False)

    # Voice notes: the speech model runs in its own process, started a few
    # seconds after launch. Falls back to the typed dialog if unavailable.
    voice = VoiceNotes(
        voice_config(config),
        hotkeys,
        save_callback=notion.add_todo,
        fallback=window.add_todo,
        finish_hint=lambda: hotkeys_from_config(config)["new_todo"] or "the hotkey",
        on_saved=window.refresh,
    )
    settings_listeners.append(lambda cfg: voice.apply_settings(voice_config(cfg)))

    actions = {
        "new_todo": voice.toggle,
        "toggle_dashboard": window.toggle_dashboard,
        "toggle_clock": window.toggle_clock,
        VoiceNotes.ESC_NAME: voice.cancel,
    }
    hotkeys.triggered.connect(lambda name: actions[name]())
    apply_hotkeys(hotkeys, config, window)
    qt_app.aboutToQuit.connect(voice.shutdown)
    qt_app.aboutToQuit.connect(hotkeys.unregister_all)

    if tray is None or not config["app"].get("start_minimized", False):
        window.show()

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
