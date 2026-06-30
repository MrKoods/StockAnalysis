"""
State persistence for paper trading positions.
Mirrors portfolio_manager.py but uses data/processed/paper_positions.json.
"""

import json
from pathlib import Path

_PAPER_STATE_FILE = Path("data/processed/paper_positions.json")

_EMPTY_STATE = {
    "positions": [],
    "account_equity": 15000.0,
    "peak_equity": 15000.0,
    "trading_days_elapsed": 0,
    "session_start_date": None,
}


def load_paper_state() -> dict:
    if _PAPER_STATE_FILE.exists():
        return json.loads(_PAPER_STATE_FILE.read_text())
    return _EMPTY_STATE.copy()


def save_paper_state(state: dict) -> None:
    _PAPER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PAPER_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
