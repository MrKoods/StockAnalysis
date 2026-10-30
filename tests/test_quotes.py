import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import paper_runner as pr  # noqa: E402
import quotes  # noqa: E402

D1, D2 = date(2026, 11, 2), date(2026, 11, 3)


def _closed(side="long"):
    return {"ticker": "X", "side": side, "entry_px": 100.0, "exit_px": 101.0, "spy_bps": 10.0}


def test_real_price_uses_ask_to_buy_and_bid_to_sell():
    q = {(str(D1), "open", "X"): (99.9, 100.1), (str(D2), "open", "X"): (100.9, 101.1)}
    r = pr.real_price(_closed(), {"cost_bps": 10}, q, D1, D2, "open")
    assert r["real_entry_px"] == 100.1 and r["real_exit_px"] == 100.9 and r["real_legs"] == 2
    assert abs(r["real_bps"] - (100.9 / 100.1 - 1) * 1e4) < 0.01
    s = pr.real_price(_closed("short"), {"cost_bps": 10}, q, D1, D2, "open")     # short: sell bid, buy back ask
    assert s["real_entry_px"] == 99.9 and s["real_exit_px"] == 101.1


def test_real_price_falls_back_to_cost_estimate_without_quotes():
    r = pr.real_price(_closed(), {"cost_bps": 20}, {}, D1, D2, "close")
    assert r["real_legs"] == 0
    assert r["real_entry_px"] == 100.1 and r["real_exit_px"] == 100.899      # +/- half of 20 bps


def test_stream_parsing_reads_inline_and_saved_results(tmp_path):
    saved = tmp_path / "big.json"
    saved.write_text(json.dumps([{"type": "text", "text": json.dumps([{"symbol": "BIG", "bid": "1", "ask": "2"}])}]))
    lines = [
        {"type": "user", "message": {"content": [{"type": "tool_result",
                                                  "content": [{"type": "text", "text": json.dumps(
                                                      [{"symbol": "AAA", "bid": "9", "ask": "10"}])}]}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result",
                                                  "content": f"<persisted-output>\nFull output saved to: {saved}\n"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "[{\"symbol\": \"FAKE\"}]"}]}},
    ]
    got = quotes._tool_results("\n".join(json.dumps(x) for x in lines))
    assert sorted(d["symbol"] for d in got) == ["AAA", "BIG"]      # model-typed text is never trusted
