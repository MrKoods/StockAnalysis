"""
Background scan execution for the app UI. Two pieces:

- get_av_budget_status(): reads today's Alpha Vantage call count and estimates
  whether a manual run would exceed the daily budget — the guard recommended
  in App_UI_Scope.md §3.4/§6 in place of a generic confirmation dialog.
- ScanWorker: a QThread that runs paper_trading.paper_runner.run_paper_scan()
  off the Qt main thread, per App_UI_Scope.md §2/§3.4. Targets the paper
  runner, not run_swing_model.py — every model version through the current
  CHANGELOG.md entry is still marked not-yet-eligible-to-go-live.
"""

from typing import Optional

from PySide6.QtCore import QThread, Signal

from swing_model.indicator_pipeline import load_config
from swing_model.run_swing_model import _read_av_call_count


def get_av_budget_status(scan_type: str, cfg: Optional[dict] = None) -> dict:
    """
    Returns:
    {
        used: int              — AV calls already made today
        estimated: int         — calls this scan_type is budgeted to use
        daily_limit: int       — hard daily cap
        projected: int         — used + estimated
        would_exceed: bool     — projected > daily_limit
    }
    """
    cfg = cfg if cfg is not None else load_config()
    budget_cfg = cfg.get("alpha_vantage_budget", {})
    used = _read_av_call_count()
    estimated = int(budget_cfg.get(scan_type, 0))
    daily_limit = int(budget_cfg.get("daily_limit", 25))
    projected = used + estimated
    return {
        "used": used,
        "estimated": estimated,
        "daily_limit": daily_limit,
        "projected": projected,
        "would_exceed": projected > daily_limit,
    }


class ScanWorker(QThread):
    """Runs one paper-trading scan on a background thread."""

    scan_succeeded = Signal(int)   # signals_logged
    scan_failed = Signal(str)      # error message

    def __init__(self, scan_type: str, parent=None):
        super().__init__(parent)
        self.scan_type = scan_type

    def run(self) -> None:
        try:
            from paper_trading.paper_runner import run_paper_scan
            signals_logged = run_paper_scan(scan_type=self.scan_type)
            self.scan_succeeded.emit(signals_logged)
        except Exception as exc:
            self.scan_failed.emit(str(exc))
