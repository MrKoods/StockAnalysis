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
    raw = tmp_path / "raw.txt"                                    # the other format: raw payload in a .txt
    raw.write_text(json.dumps([{"symbol": "RAW", "bid": "1", "ask": "2"}]))
    lines.append({"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text",
                  "text": f"Error: result (74,485 characters) exceeds maximum allowed tokens. Output has been "
                          f"saved to {raw}.\nFormat: Plain text"}]}]}})
    got = quotes._tool_results("\n".join(json.dumps(x) for x in lines))
    assert sorted(d["symbol"] for d in got) == ["AAA", "BIG", "RAW"]   # model-typed text is never trusted


def test_signed_out_webull_connector_is_named_not_generic_failed(tmp_path, monkeypatch):
    """2026-11-13..20: the claude.ai Webull connector's OAuth expired; 6 days of 0/N quotes showed only as a
    generic FAILED. The Clerk must stop at once (no retry), say exactly what the user has to do, and exit 1."""
    from datetime import datetime
    stream = "\n".join(json.dumps(x) for x in [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ToolSearch",
                                                       "input": {"query": "select:mcp__claude_ai_Webull__get_stock_snapshot"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "No matching deferred tools found"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text":
            "Only mcp__claude_ai_Webull__authenticate is available - the Webull MCP server requires OAuth authentication."}]}},
        {"type": "result", "num_turns": 4, "total_cost_usd": 0.05},
    ])
    launches, posts = [], []
    monkeypatch.setattr(quotes, "now_pt", lambda: datetime(2026, 11, 20, 6, 31))
    monkeypatch.setattr(quotes, "too_late", lambda *a: None)
    monkeypatch.setattr(quotes, "needs", lambda *a: ["AAPL", "MSFT"])
    monkeypatch.setattr(quotes, "runs_this_week", lambda: 0)
    monkeypatch.setattr(quotes, "_launch", lambda *a: launches.append(1) or stream)
    monkeypatch.setattr(quotes, "post", lambda ch, text, who: posts.append(text))
    monkeypatch.setattr(quotes.time, "sleep", lambda s: None)
    for name in ("QUOTES", "USAGE", "INVALID"):
        monkeypatch.setattr(quotes, name, tmp_path / name)
    msg = quotes.capture("open")
    assert "0/2" in msg and "(webull_auth)" in msg
    assert len(launches) == 1                                   # retrying can't fix a signed-out connector
    assert len(posts) == 1 and "Connectors -> Webull" in posts[0]
    assert not (tmp_path / "QUOTES").exists()


def test_webull_marker_never_matches_a_good_run():
    import re
    from common import WEBULL_AUTH_RX
    good = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text",
                      "text": json.dumps([{"symbol": "AAPL", "bid": "342.5", "ask": "342.6"}])}]}]}})
    assert not re.search(WEBULL_AUTH_RX, good)


def test_every_capture_quotes_the_etfs_and_open2_follows_open(tmp_path, monkeypatch):
    monkeypatch.setattr(quotes, "ON1_LEDGER", tmp_path / "none.csv")
    monkeypatch.setattr(quotes, "EPRE_LEDGER", tmp_path / "none.csv")
    monkeypatch.setattr(pr, "REGISTRY", tmp_path / "none.json")
    for when in ("close", "open", "open2"):
        assert set(quotes.ETFS) <= set(quotes.needs(when, D1))


def test_open2_window_tries_and_stops_after_success(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(quotes, "OPEN2_STATE", tmp_path / "o2.json")
    mon = lambda h, m: datetime(2026, 11, 23, h, m)   # a Monday  # noqa: E731
    assert [quotes.open2_due(mon(h, m)) for h, m in [(6, 39), (6, 40), (6, 50), (6, 55)]] == [False, True, True, False]
    assert not quotes.open2_due(datetime(2026, 11, 28, 6, 40))                 # Saturday
    quotes.save_json(quotes.OPEN2_STATE, {"date": "2026-11-23", "tries": 1, "ok": True})
    assert not quotes.open2_due(mon(6, 50))                                    # done for today
    quotes.save_json(quotes.OPEN2_STATE, {"date": "2026-11-23", "tries": 1, "ok": False})
    assert quotes.open2_due(mon(6, 50))                                        # one more try
    quotes.save_json(quotes.OPEN2_STATE, {"date": "2026-11-23", "tries": 2, "ok": False})
    assert not quotes.open2_due(mon(6, 50))
    assert quotes.too_late("open2", mon(6, 57)) and not quotes.too_late("open2", mon(6, 50))


def test_etf_fills_half_spreads_and_real_overnight(tmp_path, monkeypatch):
    f = tmp_path / "q.csv"
    f.write_text("date,when,ticker,bid,ask,bid_size,ask_size,last,quote_time\n"
                 "2026-11-20,close,SPY,99.99,100.01,,,,\n"
                 "2026-11-23,open,SPY,100.48,100.52,,,,\n"
                 "2026-11-23,open2,SPY,100.49,100.51,,,,\n"
                 "2026-11-23,close,XYZ,1,2,,,,\n")
    monkeypatch.setattr(quotes, "QUOTES", f)
    r = quotes.etf_fills(write=False)
    assert "XYZ" not in r and abs(r["SPY"]["close"] - 1.0) < 0.01 and r["SPY"]["open"] > r["SPY"]["open2"]
    o = r["SPY"]["overnight_to_open"]                        # Friday close -> Monday open = one night
    assert o["nights"] == 1 and abs(o["real_mean_bps"] - (100.48 / 100.01 - 1) * 1e4) < 0.1
    assert o["mid_mean_bps"] > o["real_mean_bps"]
