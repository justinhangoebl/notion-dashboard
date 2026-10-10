"""First-start window: asks for the Notion token, then either creates a new
PhD dashboard in Notion or lets the user pick existing databases."""

from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from notion_dashboard.notion.setup import (
    NotionItem,
    Workspace,
    config_for_existing,
    create_workspace,
    friendly_error,
    load_workspace,
    merge_config,
)
from notion_dashboard.paths import ENV_PATH
from notion_dashboard.ui.icons import ICON_ADD, ICON_DASHBOARD, ICON_LINK
from notion_dashboard.ui.settings_dialog import dialog_stylesheet
from notion_dashboard.ui.title_bar import FramelessDialog

INTEGRATIONS_URL = "https://www.notion.so/profile/integrations"



class SetupWizard(FramelessDialog):
    """Two steps: connect (token) and choose (create new / use existing).

    On accept, `result_token` and `result_config` hold what to save.
    """

    _loaded = pyqtSignal(object)  # Workspace
    _created = pyqtSignal(dict)
    _failed = pyqtSignal(str)

    def __init__(self, config: dict, colors: dict, token: str = "", parent: QWidget | None = None):
        super().__init__("Set up Notion Dashboard", colors, parent)

        self.setModal(True)
        self.setFixedWidth(440)

        self._config = config or {}
        self._colors = colors
        self._workspace: Workspace | None = None
        self.result_token = ""
        self.result_config: dict | None = None

        self.setStyleSheet(
            dialog_stylesheet(colors)
            + f"""
            QRadioButton {{
                color: {colors["text"]};
                font-family: "Segoe UI";
                font-size: 9pt;
                font-weight: 600;
                spacing: 8px;
            }}

            QRadioButton::indicator {{
                width: 12px;
                height: 12px;
                border-radius: 7px;
                border: 1px solid {colors["border"]};
                background: {colors["panel"]};
            }}

            QRadioButton::indicator:checked {{
                border: 4px solid {colors["accent"]};
                width: 6px;
                height: 6px;
                background: white;
            }}

            QLabel#statusText {{
                color: {colors["muted"]};
                font-size: 8pt;
            }}

            QPushButton:disabled {{
                color: {colors["muted"]};
            }}

            QPushButton#saveButton:disabled {{
                background: {colors["border"]};
                border: 1px solid {colors["border"]};
            }}
            """
        )

        self._loaded.connect(self._on_loaded)
        self._created.connect(self._on_created)
        self._failed.connect(self._on_failed)

        root = self.content_layout
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_connect_page(token))
        self.stack.addWidget(self._build_choose_page())
        root.addWidget(self.stack)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusText")
        self.status_label.hide()
        root.addWidget(self.status_label)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.back_button = self._button("Back", self._go_back)
        self.back_button.hide()
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self._button("Cancel", self.reject))

        self.next_button = self._button("Connect", self._on_next)
        self.next_button.setObjectName("saveButton")
        self.next_button.setDefault(True)
        buttons.addWidget(self.next_button)

        root.addLayout(buttons)
        self._show_page(0)

    # ---- pages ------------------------------------------------------------

    def _build_connect_page(self, token: str) -> QWidget:
        page, layout = self._card(ICON_LINK, "Connect to Notion")

        accent = self._colors["accent"]
        steps = QLabel(
            f"1. Open <a href='{INTEGRATIONS_URL}' style='color:{accent}'>notion.so/profile/integrations</a> "
            "and create an <b>internal</b> integration.<br>"
            "2. Under Capabilities, enable <b>Read</b>, <b>Update</b> and <b>Insert content</b>.<br>"
            "3. Copy the <b>Internal Integration Secret</b> and paste it below.<br>"
            "4. In Notion, open the page the dashboard should live in and add the "
            "integration under <b>••• → Connections</b>."
        )
        steps.setWordWrap(True)
        steps.setOpenExternalLinks(True)
        steps.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(steps)

        self.token_edit = QLineEdit(token)
        self.token_edit.setPlaceholderText("ntn_...")
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.token_edit)

        show = QCheckBox("Show token")
        show.toggled.connect(
            lambda on: self.token_edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        )
        layout.addWidget(show)

        layout.addWidget(self._hint(f"The token is stored only on this PC, in {ENV_PATH}."))
        return page

    def _build_choose_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.mode_group = QButtonGroup(self)

        # ---- create new ---------------------------------------------------
        card, card_layout = self._card(ICON_ADD, "")
        self.create_radio = QRadioButton("Create a new PhD dashboard")
        self.mode_group.addButton(self.create_radio)
        self._replace_title(card_layout, self.create_radio)

        self.create_form = QWidget()
        form = self._form(self.create_form)
        self.parent_combo = self._combo()
        form.addRow("Inside page", self.parent_combo)
        self.name_edit = QLineEdit("PhD Dashboard")
        form.addRow("Name", self.name_edit)
        card_layout.addWidget(self.create_form)
        card_layout.addWidget(self._hint("Adds a page with a Calendar and a TODO database, ready to use."))
        layout.addWidget(card)

        # ---- use existing -------------------------------------------------
        card, card_layout = self._card(ICON_DASHBOARD, "")
        self.existing_radio = QRadioButton("Use existing databases")
        self.mode_group.addButton(self.existing_radio)
        self._replace_title(card_layout, self.existing_radio)

        self.existing_form = QWidget()
        form = self._form(self.existing_form)
        self.calendar_combo = self._combo()
        form.addRow("Calendar", self.calendar_combo)
        self.todo_combo = self._combo()
        form.addRow("TODOs", self.todo_combo)
        card_layout.addWidget(self.existing_form)
        card_layout.addWidget(self._hint("Property names are detected automatically. Check config.yaml afterwards."))
        layout.addWidget(card)

        self.create_radio.toggled.connect(self._update_mode)
        self.create_radio.setChecked(True)

        # ---- reload -------------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(8)
        self.workspace_label = self._hint("")
        row.addWidget(self.workspace_label, stretch=1)
        self.reload_button = self._button("Reload", self._connect)
        row.addWidget(self.reload_button)
        layout.addLayout(row)

        return page

    # ---- flow -------------------------------------------------------------

    def _show_page(self, index: int):
        self.stack.setCurrentIndex(index)
        self.back_button.setVisible(index == 1)
        self.next_button.setText("Connect" if index == 0 else "Finish")
        self.error_label.hide()
        # The stack would otherwise keep the height of its tallest page.
        for i in range(self.stack.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self.stack.widget(i).setSizePolicy(policy, policy)
        self.stack.adjustSize()
        self.adjustSize()

    def _go_back(self):
        self._show_page(0)

    def _on_next(self):
        if self.stack.currentIndex() == 0:
            self._connect()
        else:
            self._finish()

    def _connect(self):
        token = self.token_edit.text().strip()
        if not token:
            self._show_error("Paste your integration token first.")
            return

        self._run("Connecting to Notion…", lambda: self._loaded.emit(load_workspace(token)))

    def _on_loaded(self, workspace: Workspace):
        self._set_busy(None)
        self._workspace = workspace
        notion_cfg = self._config.get("notion", {})

        self._fill(self.parent_combo, workspace.pages, "")
        self._fill(self.calendar_combo, workspace.data_sources, notion_cfg.get("calendar_data_source_id", ""), "calendar")
        self._fill(self.todo_combo, workspace.data_sources, notion_cfg.get("todo_data_source_id", ""), "todo", "task")

        has_existing = self.calendar_combo.currentIndex() >= 0 and self.todo_combo.currentIndex() >= 0
        likely_existing = has_existing and self.calendar_combo.currentIndex() != self.todo_combo.currentIndex()
        (self.existing_radio if likely_existing else self.create_radio).setChecked(True)
        self.existing_radio.setEnabled(len(workspace.data_sources) >= 2)

        who = f"Connected as {workspace.bot_name}. " if workspace.bot_name else ""
        if not workspace.pages:
            self.workspace_label.setText(
                who + "No pages shared yet. In Notion: open a page → ••• → Connections → add the integration, "
                "then Reload."
            )
        else:
            self.workspace_label.setText(who + "Missing a page? Share it with the integration (••• → Connections).")

        self._show_page(1)

    def _finish(self):
        token = self.token_edit.text().strip()

        if self.create_radio.isChecked():
            parent: NotionItem | None = self.parent_combo.currentData()
            name = self.name_edit.text().strip() or "PhD Dashboard"
            if parent is None:
                self._show_error("Choose the page to create the dashboard in.")
                return
            work = lambda: create_workspace(token, parent.id, name)
            status = f"Creating “{name}” in {parent.title}…"
        else:
            calendar: NotionItem | None = self.calendar_combo.currentData()
            todo: NotionItem | None = self.todo_combo.currentData()
            if calendar is None or todo is None:
                self._show_error("Choose a Calendar and a TODO database.")
                return
            if calendar.id == todo.id:
                self._show_error("Calendar and TODOs must be different databases.")
                return
            page_url = self._config.get("notion", {}).get("phd_page_url", "")
            work = lambda: config_for_existing(token, calendar.id, todo.id, page_url)
            status = "Reading the databases…"

        self._run(status, lambda: self._created.emit(work()))

    def _on_created(self, sections: dict):
        self._set_busy(None)
        self.result_token = self.token_edit.text().strip()
        self.result_config = merge_config(self._config, sections)
        self.accept()

    def _on_failed(self, message: str):
        self._set_busy(None)
        self._show_error(message)

    # ---- background work --------------------------------------------------

    def _run(self, status: str, fn: Callable[[], None]):
        self._set_busy(status)

        def worker():
            try:
                fn()
            except Exception as exc:
                self._failed.emit(friendly_error(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, status: str | None):
        busy = status is not None
        for widget in (self.next_button, self.back_button, self.reload_button, self.stack):
            widget.setEnabled(not busy)
        self.status_label.setText(status or "")
        self.status_label.setVisible(busy)
        if busy:
            self.error_label.hide()

    def _show_error(self, text: str):
        self.error_label.setText(text)
        self.error_label.show()

    # ---- helpers ----------------------------------------------------------

    def _update_mode(self):
        create = self.create_radio.isChecked()
        self.create_form.setEnabled(create)
        self.existing_form.setEnabled(not create)

    @staticmethod
    def _fill(combo: QComboBox, items: list[NotionItem], selected_id: str, *keywords: str):
        """Fills a combo, selecting `selected_id`, else the first item whose
        title contains one of `keywords`, else nothing (or the first item
        when no keywords are given)."""

        combo.clear()
        for item in items:
            combo.addItem(item.title, item)

        def norm(value: str) -> str:
            return value.replace("-", "")

        index = next((i for i, x in enumerate(items) if selected_id and norm(x.id) == norm(selected_id)), -1)
        if index < 0 and keywords:
            index = next((i for i, x in enumerate(items) if any(k in x.title.casefold() for k in keywords)), -1)
        elif index < 0 and items:
            index = 0
        combo.setCurrentIndex(index)

    def _card(self, icon: str, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_label = QLabel(icon)
        icon_label.setObjectName("sectionIcon")
        header.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        header.addWidget(title_label, stretch=1)
        layout.addLayout(header)
        return card, layout

    @staticmethod
    def _replace_title(card_layout: QVBoxLayout, widget: QWidget):
        """Swaps a card's title label for `widget` (a radio button)."""
        header = card_layout.itemAt(0).layout()
        old = header.itemAt(1).widget()
        header.replaceWidget(old, widget)
        old.deleteLater()

    @staticmethod
    def _form(host: QWidget) -> QFormLayout:
        form = QFormLayout(host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    @staticmethod
    def _combo() -> QComboBox:
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(16)
        combo.setMaxVisibleItems(15)
        return combo

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintText")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _button(text: str, slot: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button
