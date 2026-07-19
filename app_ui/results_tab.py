"""
Results screen — App_UI_Scope.md §3.1. Watchlist tickers for a chosen scan run,
grouped by outcome category, each expandable to its 5-category + modifier
layer breakdown. Historical runs are browsable via a run-date selector that
pulls from the DB, not just the latest run.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app_ui import db

_CATEGORY_LABELS = {
    db.CATEGORY_TRADE_RECOMMENDED: "Trade Recommended",
    db.CATEGORY_PASSED_NO_TRADE: "Passed Filters, No Trade",
    db.CATEGORY_NEAR_MISS: "Near-Miss",
    db.CATEGORY_NO_SIGNAL: "No Signal",
}
_CATEGORY_ORDER = [
    db.CATEGORY_TRADE_RECOMMENDED, db.CATEGORY_PASSED_NO_TRADE,
    db.CATEGORY_NEAR_MISS, db.CATEGORY_NO_SIGNAL,
]

_LAYER_LABELS = {
    "technical": "Technical (0-40)",
    "market_positioning": "Market Positioning (0-20)",
    "sentiment": "Sentiment (0-15)",
    "news": "News (0-15)",
    "fundamental": "Fundamental (0-10)",
    "regime": "Regime modifier",
    "sector_rotation": "Sector rotation modifier",
    "earnings": "Earnings modifier",
    "cross_ticker": "Cross-ticker modifier",
    "seasonality": "Seasonality modifier",
    "macro_overlay": "Macro overlay modifier",
}
_LAYER_ORDER = [
    "technical", "market_positioning", "sentiment", "news", "fundamental",
    "regime", "sector_rotation", "earnings", "cross_ticker", "seasonality", "macro_overlay",
]


class ResultsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._run_ids: list[int] = []

        self.run_selector = QComboBox()
        self.run_selector.currentIndexChanged.connect(self._on_run_selected)

        header = QHBoxLayout()
        header.addWidget(QLabel("Scan run:"))
        header.addWidget(self.run_selector, stretch=1)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Ticker / Layer", "Score", "Structure", "EV", "Event Gate"])
        self.tree.setColumnWidth(0, 260)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.tree)

        self.reload_runs()

    def reload_runs(self) -> None:
        """Repopulate the run-date selector from the DB and show the latest run."""
        runs = db.list_scan_runs()
        self._run_ids = [r["run_id"] for r in runs]
        self.run_selector.blockSignals(True)
        self.run_selector.clear()
        for r in runs:
            self.run_selector.addItem(f"{r['run_timestamp']}  ({r['scan_type']})", userData=r["run_id"])
        self.run_selector.blockSignals(False)
        if runs:
            self.run_selector.setCurrentIndex(0)
            self._render_run(runs[0]["run_id"])
        else:
            self.tree.clear()

    def _on_run_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._run_ids):
            return
        self._render_run(self._run_ids[index])

    def _render_run(self, run_id: int) -> None:
        self.tree.clear()
        results = db.get_ticker_results(run_id)
        by_category: dict[str, list[dict]] = {cat: [] for cat in _CATEGORY_ORDER}
        for row in results:
            by_category.setdefault(row["category"], []).append(row)

        for category in _CATEGORY_ORDER:
            rows = sorted(by_category.get(category, []), key=lambda r: -(r["composite_score"] or 0))
            category_item = QTreeWidgetItem([f"{_CATEGORY_LABELS[category]}  ({len(rows)})"])
            category_item.setFirstColumnSpanned(True)
            font = category_item.font(0)
            font.setBold(True)
            category_item.setFont(0, font)
            self.tree.addTopLevelItem(category_item)

            for row in rows:
                gate_flag = "⚠ Active Event" if row["event_gate_blocked"] else ""
                ticker_item = QTreeWidgetItem([
                    row["ticker"],
                    f"{row['composite_score']:.1f}" if row["composite_score"] is not None else "",
                    row["trade_structure"] or "",
                    f"{row['expected_value']:.4f}" if row["expected_value"] is not None else "",
                    gate_flag,
                ])
                if gate_flag:
                    ticker_item.setForeground(4, Qt.GlobalColor.darkYellow)
                category_item.addChild(ticker_item)

                layers = sorted(
                    db.get_layer_scores(row["result_id"]),
                    key=lambda layer: _LAYER_ORDER.index(layer["layer_name"])
                    if layer["layer_name"] in _LAYER_ORDER else len(_LAYER_ORDER),
                )
                for layer in layers:
                    layer_name = layer["layer_name"]
                    label = _LAYER_LABELS.get(layer_name, layer_name)
                    score = layer["score"]
                    layer_item = QTreeWidgetItem([
                        label, f"{score:+.1f}" if score is not None else "", "", "", "",
                    ])
                    ticker_item.addChild(layer_item)

            category_item.setExpanded(True)

        self.tree.expandToDepth(0)
