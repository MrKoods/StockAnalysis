"""
Config screen — App_UI_Scope.md §3.3. Editable view of swing_config.yaml.
Edits write back to the YAML file directly (config stays the pipeline's single
source of truth); validation runs before every save so a bad edit can't
silently break a run.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from app_ui.config_validation import validate_config_text

DEFAULT_CONFIG_PATH = Path("config/swing_config.yaml")


class ConfigTab(QWidget):
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH, parent=None):
        super().__init__(parent)
        self.config_path = config_path

        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self.editor.font()
        font.setFamily("Consolas")
        self.editor.setFont(font)

        self.status_label = QLabel("")
        self.reload_button = QPushButton("Reload")
        self.save_button = QPushButton("Save")
        self.reload_button.clicked.connect(self.reload_from_disk)
        self.save_button.clicked.connect(self.save_to_disk)

        buttons = QHBoxLayout()
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(str(self.config_path)))
        layout.addWidget(self.editor)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)

        self.reload_from_disk()

    def reload_from_disk(self) -> None:
        try:
            text = self.config_path.read_text(encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(f"Could not read {self.config_path}: {exc}")
            return
        self.editor.setPlainText(text)
        self.status_label.setText("Loaded.")

    def save_to_disk(self) -> None:
        text = self.editor.toPlainText()
        is_valid, errors = validate_config_text(text)
        if not is_valid:
            self.status_label.setText(f"NOT saved — {len(errors)} validation error(s).")
            QMessageBox.warning(
                self, "Config validation failed",
                "Fix the following before saving:\n\n" + "\n".join(f"• {e}" for e in errors),
            )
            return
        try:
            self.config_path.write_text(text, encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(f"Save failed: {exc}")
            return
        self.status_label.setText("Saved.")
