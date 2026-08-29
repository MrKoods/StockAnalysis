"""Tests for scripts/check_no_raw_http.py — the CI gate keeping external fetches inside shared/api_clients/."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_no_raw_http.py"
_spec = importlib.util.spec_from_file_location("check_no_raw_http", _SCRIPT)
check_no_raw_http = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_no_raw_http)


def _write(tmp_path, rel, body):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_flags_raw_requests_call(tmp_path):
    p = _write(tmp_path, "swing_model/x.py", "import requests\nr = requests.get('http://x')\n")
    hits = check_no_raw_http.check_file(p)
    assert any("raw HTTP call" in h for h in hits)


def test_flags_direct_yfinance(tmp_path):
    p = _write(tmp_path, "swing_model/x.py", "import yfinance as yf\ndf = yf.download('NVDA')\n")
    hits = check_no_raw_http.check_file(p)
    assert any("direct yfinance use" in h for h in hits)


def test_ignores_yf_in_comments_and_docstrings(tmp_path):
    p = _write(tmp_path, "swing_model/x.py",
               '"""This module used to call yf.download directly."""\n'
               "# yf.Ticker(t).calendar was the old path\n"
               "x = 1\n")
    assert check_no_raw_http.check_file(p) == []


def test_clean_file_passes(tmp_path):
    p = _write(tmp_path, "swing_model/x.py",
               "from shared.api_clients.market_data_client import fetch_ohlcv\ndf = fetch_ohlcv('NVDA')\n")
    assert check_no_raw_http.check_file(p) == []


def test_the_real_repo_is_clean():
    """The live scan path must have zero violations — this is the guarantee."""
    assert check_no_raw_http.main() == 0


def test_prose_helper():
    text = "    # yf.download here\n    yf.download('X')\n"
    comment_pos = text.index("yf.", 0)
    real_pos = text.index("yf.", comment_pos + 1)
    assert check_no_raw_http._looks_like_prose(text, comment_pos) is True
    assert check_no_raw_http._looks_like_prose(text, real_pos) is False
