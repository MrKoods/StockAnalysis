import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ideas  # noqa: E402


def test_cost_hurdle_needs_three_times_cost_and_a_real_cost():
    assert ideas.cost_hurdle(60, 20) is None
    assert "3 x" in ideas.cost_hurdle(50, 20)
    assert "below the cheapest" in ideas.cost_hurdle(100, 1)
    assert "numbers" in ideas.cost_hurdle("big", 20)


def test_add_refuses_thin_ideas_and_records_gross(tmp_path, monkeypatch):
    monkeypatch.setattr(ideas, "IDEAS", tmp_path / "ideas.csv")
    base = ["add", "--id", "abc", "--family", "f", "--horizon", "5d", "--summary", "s", "--mechanism", "m",
            "--data", "d", "--cost", "20"]
    with pytest.raises(SystemExit, match="refused"):
        ideas.main(base + ["--gross", "40"])
    assert not (tmp_path / "ideas.csv").exists()
    ideas.main(base + ["--gross", "75"])
    assert ideas.get("abc")["est_gross_bps"] == "75"
