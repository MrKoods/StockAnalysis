"""
Tests for scripts/check_rank_track_slot_budget.py — the standing guardrail
against the v2.2.100 rank-track over-logging bug.

Proven against the real bad example: run against the pre-fix ledger backed up
on 2026-08-26, it reports all 4 sectors at 6 rows against a budget of 2 and
exits 1. These lock in that behaviour plus the branches around it (missing
file, empty ledger, unmapped tickers) so the gate can't be quietly softened
into something that always passes.
"""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_rank_track_slot_budget.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_rank_slot_checker", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONFIG_YAML = """
rank_track:
  top_n_per_sector: 2
watchlist:
  sectors:
    semiconductors:
      active: true
      benchmark: SMH
      tickers: [MU, ADI, AMD, QCOM, ASML, NVDA]
    healthcare:
      active: true
      benchmark: XLV
      tickers: [AMGN, GILD, MRK, BMY]
"""

_COLUMNS = ["signal_date", "ticker", "confidence", "direction", "outcome"]


@pytest.fixture
def checker(tmp_path, monkeypatch):
    module = _load_checker()
    config_path = tmp_path / "swing_config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    monkeypatch.setattr(module, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(module, "_RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    return module


def _write(module, rows):
    with open(module._RANK_TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        for date, ticker in rows:
            writer.writerow({
                "signal_date": date, "ticker": ticker,
                "confidence": "50.0", "direction": "bullish", "outcome": "",
            })


class TestPasses:
    def test_missing_file_is_not_a_failure(self, checker):
        assert checker.main() == 0

    def test_empty_ledger_is_not_a_failure(self, checker):
        _write(checker, [])
        assert checker.main() == 0

    def test_exactly_top_n_per_sector_passes(self, checker):
        _write(checker, [
            ("2026-08-25", "MU"), ("2026-08-25", "ASML"),
            ("2026-08-25", "AMGN"), ("2026-08-25", "MRK"),
        ])
        assert checker.main() == 0

    def test_same_ticker_count_spread_across_days_passes(self, checker):
        """The budget is per (day, sector) — 2 a day for 3 days is fine."""
        _write(checker, [
            ("2026-08-25", "MU"), ("2026-08-25", "ASML"),
            ("2026-08-26", "ADI"), ("2026-08-26", "NVDA"),
            ("2026-08-27", "AMD"), ("2026-08-27", "QCOM"),
        ])
        assert checker.main() == 0


class TestFails:
    def test_one_over_budget_fails(self, checker):
        _write(checker, [
            ("2026-08-25", "MU"), ("2026-08-25", "ASML"), ("2026-08-25", "ADI"),
        ])
        assert checker.main() == 1

    def test_the_real_2026_08_25_shape_fails(self, checker):
        """6 per sector against a budget of 2 — exactly what was logged live."""
        _write(checker, [
            ("2026-08-25", t)
            for t in ["MU", "ADI", "AMD", "QCOM", "ASML", "NVDA"]
        ])
        assert checker.main() == 1

    def test_reports_every_offending_group(self, checker, capsys):
        _write(checker, [
            ("2026-08-25", t) for t in ["MU", "ADI", "AMD", "QCOM", "ASML", "NVDA"]
        ] + [
            ("2026-08-25", t) for t in ["AMGN", "GILD", "MRK", "BMY"]
        ])
        assert checker.main() == 1
        out = capsys.readouterr().out
        assert "semiconductors: 6 rows" in out
        assert "healthcare: 4 rows" in out


class TestUnmappedTickers:
    def test_unknown_ticker_warns_but_does_not_fail(self, checker, capsys):
        """A ticker that left the watchlist isn't evidence of a violation..."""
        _write(checker, [("2026-08-25", "DELISTED"), ("2026-08-25", "MU")])
        assert checker.main() == 0
        assert "not in any active sector" in capsys.readouterr().out

    def test_warning_says_those_rows_are_not_budget_checked(self, checker, capsys):
        """...but the report must be honest that a violation could hide there."""
        _write(checker, [("2026-08-25", "DELISTED")])
        checker.main()
        assert "could hide among" in capsys.readouterr().out
