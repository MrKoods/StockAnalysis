"""
Notifications / Alerts feed — App_UI_Scope.md §3.2. Chronological log of every
alert the pipeline sends, filterable by ticker and alert type. Discord is the
only delivery channel (see CHANGELOG.md v2.2.1), so there's a single delivery
status column, not per-channel ones.
"""

import json

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app_ui import db

_ALL = "(all)"
_COLUMNS = ["Timestamp", "Ticker", "Alert Type", "Discord Status", "Payload"]


class NotificationsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.ticker_filter = QComboBox()
        self.type_filter = QComboBox()
        self.ticker_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.currentIndexChanged.connect(self.refresh)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Ticker:"))
        filters.addWidget(self.ticker_filter)
        filters.addWidget(QLabel("Type:"))
        filters.addWidget(self.type_filter)
        filters.addStretch(1)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.table)

        self.reload_filters()

    def reload_filters(self) -> None:
        """Repopulate the ticker/type filter dropdowns from what's actually in the DB."""
        notes = db.get_notifications(limit=2000)
        tickers = sorted({n["ticker"] for n in notes if n["ticker"]})
        types = sorted({n["alert_type"] for n in notes})

        self._repopulate(self.ticker_filter, tickers)
        self._repopulate(self.type_filter, types)
        self.refresh()

    @staticmethod
    def _repopulate(combo: QComboBox, values: list[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_ALL)
        combo.addItems(values)
        idx = combo.findText(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def refresh(self) -> None:
        ticker = self.ticker_filter.currentText()
        alert_type = self.type_filter.currentText()
        notes = db.get_notifications(
            ticker=None if ticker in ("", _ALL) else ticker,
            alert_type=None if alert_type in ("", _ALL) else alert_type,
        )

        self.table.setRowCount(len(notes))
        for row_idx, note in enumerate(notes):
            payload_summary = ""
            if note["payload_json"]:
                try:
                    payload_summary = json.dumps(json.loads(note["payload_json"]))
                except (TypeError, ValueError):
                    payload_summary = str(note["payload_json"])
            values = [
                note["timestamp"] or "",
                note["ticker"] or "",
                note["alert_type"] or "",
                note["discord_status"] or "",
                payload_summary,
            ]
            for col_idx, value in enumerate(values):
                self.table.setItem(row_idx, col_idx, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
