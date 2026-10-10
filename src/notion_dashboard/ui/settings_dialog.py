"""A dark, Notion-styled dialog for editing config.yaml's app-level settings."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from notion_dashboard.hotkeys import HOTKEY_ACTIONS, hotkeys_from_config, parse_hotkey
from notion_dashboard.paths import ASSETS
from notion_dashboard.ui.icons import ICON_DASHBOARD, ICON_FONT, ICON_KEYBOARD, ICON_MICROPHONE, ICON_SETTINGS
from notion_dashboard.ui.title_bar import FramelessDialog
from notion_dashboard.voice.notes import VOICE_DEFAULTS, voice_config, voice_installed

CHECK_IMAGE = (ASSETS / "check.svg").as_posix()

VOICE_LANGUAGES = (("auto", "Auto-detect"), ("en", "English"), ("de", "German"))
VOICE_MODELS = (
    ("tiny", "tiny (fastest)"),
    ("base", "base (recommended)"),
    ("small", "small (more accurate, needs a GPU for live text)"),
)
VOICE_DEVICES = (("auto", "Auto (GPU if available)"), ("cpu", "CPU only"))

def dialog_stylesheet(colors: dict) -> str:
    """The settings look: dark cards, rounded inputs, blue primary button.
    Shared with the setup wizard."""

    return f"""
    QWidget {{
        background: transparent;
        color: {colors["text"]};
    }}

    QDialog, QWidget#dialogContent {{
        background: {colors["panel"]};
    }}

    QLabel {{
        color: {colors["text"]};
        background: transparent;
        font-family: "Segoe UI";
        font-size: 9pt;
    }}

    QLineEdit, QSpinBox {{
        background: {colors["bg"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 6px;
        padding: 5px 8px;
        font-family: "Segoe UI";
        font-size: 9pt;
    }}

    QComboBox {{
        background: {colors["bg"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 6px;
        padding: 5px 8px;
        font-family: "Segoe UI";
        font-size: 9pt;
    }}

    QComboBox:disabled, QCheckBox:disabled {{
        color: {colors["muted"]};
    }}

    QComboBox QAbstractItemView {{
        background: {colors["panel"]};
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        selection-background-color: {colors["hover"]};
        outline: none;
    }}

    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1px solid {colors["accent"]};
    }}

    QCheckBox {{
        color: {colors["text"]};
        font-family: "Segoe UI";
        font-size: 9pt;
        spacing: 8px;
    }}

    /* Drawn here rather than by the platform style: Linux's Fusion style
       draws a dark box that disappears on the dark background. */
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {colors["border"]};
        border-radius: 4px;
        background: {colors["bg"]};
    }}

    QCheckBox::indicator:checked {{
        border: 1px solid {colors["accent"]};
        background: {colors["accent"]};
        image: url("{CHECK_IMAGE}");
    }}

    QCheckBox::indicator:disabled {{
        border: 1px solid {colors["border"]};
        background: {colors["panel"]};
    }}

    QPushButton {{
        background: transparent;
        color: {colors["text"]};
        border: 1px solid {colors["border"]};
        border-radius: 6px;
        padding: 6px 16px;
        font-family: "Segoe UI";
        font-size: 9pt;
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

    QLabel#sectionIcon {{
        color: {colors["accent"]};
        font-family: "{ICON_FONT}";
        font-size: 10pt;
    }}

    QLabel#sectionTitle {{
        color: {colors["text"]};
        font-size: 10pt;
        font-weight: 600;
    }}

    QFrame#settingsCard {{
        background: {colors["bg"]};
        border: 1px solid {colors["border"]};
        border-radius: 10px;
    }}

    QFrame#settingsCard QLineEdit, QFrame#settingsCard QSpinBox,
    QFrame#settingsCard QComboBox, QFrame#settingsCard QKeySequenceEdit {{
        background: {colors["panel"]};
    }}

    QFrame#cardDivider {{
        background: {colors["border"]};
        border: none;
    }}

    QLabel#hintText {{
        color: {colors["muted"]};
        font-size: 8pt;
    }}

    QLabel#errorText {{
        color: #ff7369;
        font-size: 8pt;
    }}

    QScrollArea {{
        border: none;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0px;
        border: none;
    }}

    QScrollBar::handle:vertical {{
        background: {colors["border"]};
        min-height: 30px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {colors["accent"]};
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
    """


class SettingsDialog(FramelessDialog):
    """Edits the `app` (and `notion.phd_page_url`) section of config.yaml.

    Notion IDs / database property names are left out on purpose - those
    come from the setup window (notion-dashboard --setup), and getting one wrong would break the dashboard.
    """

    def __init__(self, config: dict, colors: dict, parent: QWidget | None = None, hotkey_note: str = ""):
        super().__init__("Settings", colors, parent)

        self.setModal(True)

        self._config = config
        self.result_config: dict | None = None

        self.setStyleSheet(dialog_stylesheet(colors))

        root = self.content_layout
        root.setContentsMargins(0, 12, 0, 16)
        root.setSpacing(12)

        # Sections are cards in a scroll area; the error line and the
        # buttons stay pinned below it.
        cards = QWidget()
        self._cards = QVBoxLayout(cards)
        self._cards.setContentsMargins(20, 4, 14, 4)
        self._cards.setSpacing(10)
        self._forms: list[QFormLayout] = []

        app_cfg = config.get("app", {})
        notion_cfg = config.get("notion", {})

        # ---- General ------------------------------------------------------

        form = self._section(ICON_SETTINGS, "General")

        self.page_url_edit = QLineEdit(notion_cfg.get("phd_page_url", ""))
        self.page_url_edit.setPlaceholderText("https://notion.so/...")
        form.addRow("Notion page URL", self.page_url_edit)

        self.open_on_start_check = QCheckBox("Open Notion page on start")
        self.open_on_start_check.setChecked(bool(app_cfg.get("open_notion_on_start", True)))
        form.addRow("", self.open_on_start_check)

        self.start_minimized_check = QCheckBox("Start minimized")
        self.start_minimized_check.setChecked(bool(app_cfg.get("start_minimized", False)))
        form.addRow("", self.start_minimized_check)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(1, 120)
        self.refresh_spin.setSuffix(" min")
        self.refresh_spin.setValue(int(app_cfg.get("refresh_minutes", 5)))
        form.addRow("Refresh interval", self.refresh_spin)

        # ---- Dashboard ----------------------------------------------------

        form = self._section(ICON_DASHBOARD, "Dashboard")

        self.max_meetings_spin = QSpinBox()
        self.max_meetings_spin.setRange(1, 50)
        self.max_meetings_spin.setValue(int(app_cfg.get("max_meetings", 10)))
        form.addRow("Max meetings shown", self.max_meetings_spin)

        self.max_todos_spin = QSpinBox()
        self.max_todos_spin.setRange(1, 50)
        self.max_todos_spin.setValue(int(app_cfg.get("max_todos", 12)))
        form.addRow("Max TODOs shown", self.max_todos_spin)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(360, 2000)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(int(app_cfg.get("window_width", 520)))
        form.addRow("Window width", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(360, 2000)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(int(app_cfg.get("window_height", 760)))
        form.addRow("Window height", self.height_spin)

        # ---- Voice notes --------------------------------------------------

        form = self._section(ICON_MICROPHONE, "Voice notes")

        voice = voice_config(config)
        self.voice_settings = voice

        self.voice_enabled_check = QCheckBox("Dictate new TODOs by voice")
        self.voice_enabled_check.setChecked(bool(voice["enabled"]))
        form.addRow("", self.voice_enabled_check)

        self.voice_combos: dict[str, QComboBox] = {}
        for key, label, options in (
            ("language", "Language", VOICE_LANGUAGES),
            ("model", "Speech model", VOICE_MODELS),
            ("device", "Run on", VOICE_DEVICES),
        ):
            combo = QComboBox()
            # Otherwise the longest option sets the width and the card overflows.
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            for value, text in options:
                combo.addItem(text, value)
            index = combo.findData(voice[key])
            combo.setCurrentIndex(index if index >= 0 else 0)
            form.addRow(label, combo)
            self.voice_combos[key] = combo

        form.addRow(self._divider())

        self.cleanup_check = QCheckBox("Tidy up notes and add a heading")
        self.cleanup_check.setChecked(bool(voice["cleanup"]))
        form.addRow("", self.cleanup_check)

        self.cleanup_model_edit = QLineEdit(str(voice["cleanup_model"]))
        self.cleanup_model_edit.setPlaceholderText(VOICE_DEFAULTS["cleanup_model"])
        self.cleanup_model_edit.setEnabled(self.cleanup_check.isChecked())
        self.cleanup_check.toggled.connect(self.cleanup_model_edit.setEnabled)
        form.addRow("Cleanup model", self.cleanup_model_edit)
        form.addRow(self._hint("Runs locally with Ollama. Notes are saved as dictated if Ollama isn't running."))

        if not voice_installed():
            for widget in (self.voice_enabled_check, *self.voice_combos.values(), self.cleanup_check, self.cleanup_model_edit):
                widget.setEnabled(False)
            form.addRow(self._hint("Voice packages aren't installed. Run:  pip install -e '.[voice]'"))

        # ---- Hotkeys ------------------------------------------------------

        form = self._section(ICON_KEYBOARD, "Hotkeys")

        self.hotkey_edits: dict[str, QKeySequenceEdit] = {}
        for name, text in hotkeys_from_config(config).items():
            edit = QKeySequenceEdit(QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            form.addRow(HOTKEY_ACTIONS[name][0], edit)
            self.hotkey_edits[name] = edit

        form.addRow(self._hint("Click a field and press the new combination. Clear it to turn the hotkey off."))
        if hotkey_note:
            form.addRow(self._hint(hotkey_note))

        self._cards.addStretch(1)
        self._align_labels()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(cards)
        # As tall as the content, but never taller than the screen allows.
        screen = (parent.screen() if parent else None) or QGuiApplication.primaryScreen()
        max_height = max(300, screen.availableGeometry().height() - 200)
        scroll.setFixedHeight(min(cards.sizeHint().height() + 8, max_height, 460))
        root.addWidget(scroll)
        # 400 px fits Segoe UI; wider fonts (e.g. DejaVu Sans on Linux) need more.
        self.setFixedWidth(max(400, cards.sizeHint().width() + 12))

        bottom = QVBoxLayout()
        bottom.setContentsMargins(20, 0, 20, 0)
        bottom.setSpacing(10)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        bottom.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        save_button = QPushButton("Save")
        save_button.setObjectName("saveButton")
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.clicked.connect(self._on_save)
        buttons.addWidget(save_button)

        bottom.addLayout(buttons)
        root.addLayout(bottom)

    # ---- layout helpers -------------------------------------------------

    def _section(self, icon: str, title: str) -> QFormLayout:
        """Adds a card with an icon + title header; returns its form."""

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
        header.addWidget(title_label)
        header.addStretch(1)
        layout.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self._cards.addWidget(card)
        self._forms.append(form)
        return form

    def _align_labels(self):
        """Gives every card the same label column, so fields line up."""
        labels = [
            item.widget()
            for form in self._forms
            for row in range(form.rowCount())
            if (item := form.itemAt(row, QFormLayout.ItemRole.LabelRole)) and item.widget()
        ]
        width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setFixedWidth(width)

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setObjectName("cardDivider")
        line.setFixedHeight(1)
        return line

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintText")
        label.setWordWrap(True)
        return label

    def _read_hotkeys(self) -> dict[str, str] | None:
        hotkeys = {}
        seen: dict[str, str] = {}

        for name, edit in self.hotkey_edits.items():
            text = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            label = HOTKEY_ACTIONS[name][0]

            if text and parse_hotkey(text) is None:
                self._show_error(f"{label}: {text} needs Ctrl, Alt or Win plus a letter, digit or F-key.")
                return None
            if text and text in seen:
                self._show_error(f"{label} and {seen[text]} both use {text}.")
                return None

            if text:
                seen[text] = label
            hotkeys[name] = text

        return hotkeys

    def _show_error(self, text: str):
        self.error_label.setText(text)
        self.error_label.show()

    def _on_save(self):
        hotkeys = self._read_hotkeys()
        if hotkeys is None:
            return

        config = dict(self._config)
        config["hotkeys"] = hotkeys
        config["voice"] = {
            **self.voice_settings,
            "enabled": self.voice_enabled_check.isChecked(),
            **{key: combo.currentData() for key, combo in self.voice_combos.items()},
            "cleanup": self.cleanup_check.isChecked(),
            "cleanup_model": self.cleanup_model_edit.text().strip() or VOICE_DEFAULTS["cleanup_model"],
        }
        config["notion"] = dict(config.get("notion", {}))
        config["app"] = dict(config.get("app", {}))

        config["notion"]["phd_page_url"] = self.page_url_edit.text().strip()
        config["app"]["open_notion_on_start"] = self.open_on_start_check.isChecked()
        config["app"]["start_minimized"] = self.start_minimized_check.isChecked()
        config["app"]["refresh_minutes"] = self.refresh_spin.value()
        config["app"]["max_meetings"] = self.max_meetings_spin.value()
        config["app"]["max_todos"] = self.max_todos_spin.value()
        config["app"]["window_width"] = self.width_spin.value()
        config["app"]["window_height"] = self.height_spin.value()

        self.result_config = config
        self.accept()
