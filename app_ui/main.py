"""
Desktop app UI entry point (App_UI_Scope.md). Run with:
    python -m app_ui.main
"""

import sys

# Load .env before any imports that read environment variables (DISCORD_WEBHOOK_URL,
# API keys) — mirrors paper_runner.py / run_swing_model.py's own startup order.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from PySide6.QtWidgets import QApplication

from app_ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("StockAnalysis")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
