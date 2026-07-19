"""
Main window — App_UI_Scope.md §3.4. Run control (scan-type selector, Run
Scan button, AV budget guard, progress indicator) lives above the tabs so
it's available from any screen, per the scope doc.
"""

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from app_ui.config_tab import ConfigTab
from app_ui.notifications_tab import NotificationsTab
from app_ui.results_tab import ResultsTab
from app_ui.scan_worker import ScanWorker, get_av_budget_status

_SCAN_TYPES = ["pre_market", "mid_session", "post_close"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StockAnalysis")
        self.resize(1100, 700)

        self._worker: ScanWorker | None = None

        self.scan_type_selector = QComboBox()
        self.scan_type_selector.addItems(_SCAN_TYPES)
        self.scan_type_selector.setCurrentText("post_close")

        self.run_button = QPushButton("Run Scan")
        self.run_button.clicked.connect(self._on_run_clicked)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(150)

        self.status_label = QLabel("")

        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("Scan type:"))
        run_row.addWidget(self.scan_type_selector)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.progress_bar)
        run_row.addWidget(self.status_label, stretch=1)

        self.results_tab = ResultsTab()
        self.notifications_tab = NotificationsTab()
        self.config_tab = ConfigTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.results_tab, "Results")
        self.tabs.addTab(self.notifications_tab, "Notifications")
        self.tabs.addTab(self.config_tab, "Config")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(run_row)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

    def _on_run_clicked(self) -> None:
        scan_type = self.scan_type_selector.currentText()
        budget = get_av_budget_status(scan_type)

        if budget["would_exceed"]:
            proceed = QMessageBox.warning(
                self, "Alpha Vantage budget",
                (
                    f"{budget['used']}/{budget['daily_limit']} AV calls used today. "
                    f"This {scan_type} run is budgeted for ~{budget['estimated']} more, "
                    f"projecting {budget['projected']}/{budget['daily_limit']} — "
                    "over the daily limit.\n\nRun anyway?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return
        else:
            self.status_label.setText(
                f"{budget['used']}/{budget['daily_limit']} AV calls used today "
                f"— this run will use ~{budget['estimated']} more."
            )

        self._start_scan(scan_type)

    def _start_scan(self, scan_type: str) -> None:
        self.run_button.setEnabled(False)
        self.scan_type_selector.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Running {scan_type} scan...")

        self._worker = ScanWorker(scan_type)
        self._worker.scan_succeeded.connect(self._on_scan_succeeded)
        self._worker.scan_failed.connect(self._on_scan_failed)
        self._worker.start()

    def _on_scan_succeeded(self, signals_logged: int) -> None:
        self._reset_run_controls()
        self.status_label.setText(f"Scan complete — {signals_logged} new signal(s) logged.")
        self.results_tab.reload_runs()
        self.notifications_tab.reload_filters()

    def _on_scan_failed(self, message: str) -> None:
        self._reset_run_controls()
        self.status_label.setText("Scan failed.")
        QMessageBox.critical(self, "Scan failed", message)

    def _reset_run_controls(self) -> None:
        self.run_button.setEnabled(True)
        self.scan_type_selector.setEnabled(True)
        self.progress_bar.setVisible(False)
