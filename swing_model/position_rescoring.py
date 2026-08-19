"""
Re-scores open positions daily; flags early exit when confidence drops significantly
post-entry. Tracks confidence time series for each open position throughout the
1-15 day holding window. Fires early exit Discord alert if confidence drops > 10 points.
"""

from datetime import datetime, timezone
from typing import Optional

from swing_model.scoring import compute_confidence_score
from shared.utils.risk_reward import compute_trailing_stop
from shared.utils.earnings_calendar import get_earnings_modifier

# Used when the caller hasn't re-fetched sentiment/news for a ticker's rescore —
# same "unavailable data" neutral convention compute_confidence_score already
# applies elsewhere (see positioning=None / fundamental=None handling in scoring.py).
_NEUTRAL_SENTIMENT = {"sentiment_score_total": 0.0, "sentiment_offline": True}
_NEUTRAL_NEWS = {"news_score_total": 7.5}


def rescore_open_positions(
    open_positions: list[dict],
    current_indicators: dict[str, dict],
    cfg: Optional[dict] = None,
    sentiment_by_ticker: Optional[dict[str, dict]] = None,
    news_by_ticker: Optional[dict[str, dict]] = None,
    market_modifiers: Optional[dict] = None,
    earnings_date_by_ticker: Optional[dict] = None,
) -> list[dict]:
    """
    Re-score all open positions with fresh indicator data.

    For each position:
    1. Pull current indicator values for that ticker
    2. Recompute confidence score using scoring.py, at the position's OWN
       stored direction (not re-derived from today's indicators — a
       weakening bearish thesis that no longer confirms downtrend_intact
       must not silently get scored as if it were a fresh bullish candidate)
    3. Compare to entry confidence score
    4. Flag early exit if confidence drop > cfg['signal_decay']['early_exit_confidence_drop']
    5. Update trailing stop level
    6. Check time stop (Day 10 with < 30% of target profit)

    current_indicators: keyed by ticker, same shape as indicator_pipeline.run_pipeline()'s
      per-ticker output (technical fields plus '_fundamental_full'/'_positioning_full'/
      '_positioning_full_bearish'). The bearish-mirrored positioning score is selected
      automatically per position based on its own stored direction.
    sentiment_by_ticker/news_by_ticker: fresh sentiment_layer/news_layer output per
      ticker, when the caller already re-fetched it for today's scan. A ticker missing
      from these falls back to a neutral mid-point — the rescore still reflects
      technical/positioning/fundamental drift, but confidence_drop in that case is
      partly an artifact of the entry score having included real sentiment/news that
      this rescore didn't re-fetch.
    market_modifiers: optional {'regime', 'regime_modifier', 'seasonality_modifier',
      'macro_modifier'} from today's live scan. Omitted modifiers default to neutral
      (0.0) / no regime cap, since this function has no market-context data of its own.
      Values are applied as-is (already direction-signed by the caller, same convention
      run_swing_model.py/paper_runner.py use) — not re-derived per position here.
    earnings_date_by_ticker: optional {ticker: next earnings date}, when the caller
      already has it (e.g. paper_updater.py's own per-ticker fetch for
      _check_earnings_exit). A ticker missing from this dict scores a neutral (0.0)
      earnings_modifier rather than this function making its own yfinance call — kept
      a pure function of its inputs, same as before. cross_ticker_modifier is left at
      0.0 regardless: a real per-ticker recompute needs the whole sector's fresh
      OHLCV, a materially more expensive rescore than this function is meant to do —
      an intentional, documented simplification, not silent parity with entry-time
      scoring (same honesty standard the backtest already holds earnings_modifier=0.0
      to when no historical archive exists for it).

    Returns list of updated position dicts with added fields:
    {
        ...original position fields...,
        current_confidence: float,
        confidence_drop: float,
        early_exit_flag: bool,
        time_stop_flag: bool,
        trailing_stop_current: float,
        days_held: int,
        pnl_pct_of_target: float,
        management_action: str,   # 'hold' | 'early_exit' | 'time_stop' | 'profit_target'
    }
    """
    if cfg is None:
        cfg = {}
    sentiment_by_ticker = sentiment_by_ticker or {}
    news_by_ticker = news_by_ticker or {}
    market_modifiers = market_modifiers or {}

    decay_cfg = cfg.get("signal_decay", {})
    early_exit_drop = float(decay_cfg.get("early_exit_confidence_drop", 10.0))
    time_stop_day = int(decay_cfg.get("time_stop_day", 10))
    # config/swing_config.yaml's real key is "time_stop_no_progress_pct" —
    # this used to read a name that doesn't exist in config, so a configured
    # value was silently never applied (harmless only by coincidence, since
    # the hardcoded default below matches config's default).
    min_progress_pct = float(decay_cfg.get("time_stop_no_progress_pct", 0.30))
    trailing_multiplier = float(decay_cfg.get("trailing_stop_atr_multiplier", 1.5))

    regime = market_modifiers.get("regime")
    regime_modifier = float(market_modifiers.get("regime_modifier", 0.0))
    seasonality_modifier = float(market_modifiers.get("seasonality_modifier", 0.0))
    macro_modifier = float(market_modifiers.get("macro_modifier", 0.0))
    earnings_date_by_ticker = earnings_date_by_ticker or {}

    results = []
    for pos in open_positions:
        if not pos.get("open", True):
            results.append(pos)
            continue

        ticker = pos.get("ticker", "")
        indicators = current_indicators.get(ticker)
        direction = pos.get("direction", "bullish")
        entry_price = float(pos.get("entry_price", 0.0))
        entry_confidence = float(pos.get("confidence", 0.0))
        days_held = _days_held(pos)

        if indicators is None:
            # No fresh data for this ticker today — can't assess decay blind; hold
            # and leave the existing stop in place rather than guess.
            result = dict(pos)
            result.update({
                "current_confidence": entry_confidence,
                "confidence_drop": 0.0,
                "early_exit_flag": False,
                "time_stop_flag": False,
                "trailing_stop_current": float(pos.get("stop_loss", 0.0)),
                "days_held": days_held,
                "pnl_pct_of_target": 0.0,
                "management_action": "hold",
                "rescore_skipped_reason": "no_current_indicators",
            })
            results.append(result)
            continue

        fundamental = indicators.get("_fundamental_full") or {}
        # Select the positioning mirror matching this position's OWN held
        # direction, not always the bullish one — same fix as direction_override
        # below (Signal Integrity Audit finding B.2).
        positioning = indicators.get(
            "_positioning_full_bearish" if direction == "bearish" else "_positioning_full"
        ) or {}
        sentiment = sentiment_by_ticker.get(ticker, _NEUTRAL_SENTIMENT)
        news = news_by_ticker.get(ticker, _NEUTRAL_NEWS)

        # Real earnings_modifier when the caller supplied today's earnings
        # date for this ticker (see earnings_date_by_ticker's docstring
        # above) — previously hardcoded 0.0 unconditionally, silently hiding
        # a real, worsening penalty (up to -20) as a position ages toward an
        # earnings print. cross_ticker_modifier stays 0.0 — documented
        # simplification, see docstring.
        earnings_date = earnings_date_by_ticker.get(ticker)
        earnings_modifier = 0.0
        if earnings_date is not None:
            earnings_modifier = get_earnings_modifier(
                ticker, earnings_date, cfg=cfg
            ).get("confidence_modifier", 0.0)

        score = compute_confidence_score(
            technical=indicators,
            positioning=positioning,
            sentiment=sentiment,
            news=news,
            regime_modifier=regime_modifier,
            sector_rotation_modifier=0.0,
            earnings_modifier=earnings_modifier,
            cross_ticker_modifier=0.0,
            seasonality_modifier=seasonality_modifier,
            macro_modifier=macro_modifier,
            cfg=cfg,
            regime=regime,
            fundamental=fundamental,
            # Honor the position's OWN stored direction rather than letting
            # compute_confidence_score re-derive it from today's indicators
            # (Signal Integrity Audit finding B.2). A bearish position whose
            # downtrend has weakened mid-hold but nothing bullish has
            # confirmed either would otherwise silently get rescored as a
            # long — exactly the "thesis weakening" case confidence_drop/
            # early_exit_flag exist to catch.
            direction_override=direction,
        )
        current_confidence = float(score.get("final_score", 0.0))
        confidence_drop = entry_confidence - current_confidence

        current_price = float(indicators.get("close", entry_price))
        pnl_pct_of_target = compute_pnl_pct_of_target(
            current_price, entry_price, float(pos.get("target", 0.0)), direction,
        )

        highest = float(pos.get("highest_close_since_entry", entry_price))
        lowest = float(pos.get("lowest_close_since_entry", entry_price))
        if direction == "bullish":
            highest = max(highest, current_price)
        else:
            lowest = min(lowest, current_price)

        atr = float(indicators.get("atr_14", 0.0))
        stop_loss = float(pos.get("stop_loss", 0.0))
        if atr > 0:
            candidate_stop = compute_trailing_stop(direction, highest, lowest, atr, trailing_multiplier)
            # Ratchet only in the position's favor — never loosen past the original stop.
            trailing_stop_current = max(candidate_stop, stop_loss) if direction == "bullish" \
                else min(candidate_stop, stop_loss)
        else:
            trailing_stop_current = stop_loss

        early_exit_flag = confidence_drop > early_exit_drop
        time_stop_flag = check_time_stop(pos, pnl_pct_of_target, days_held, time_stop_day, min_progress_pct)
        target_hit = pnl_pct_of_target >= 1.0

        if target_hit:
            management_action = "profit_target"
        elif early_exit_flag:
            management_action = "early_exit"
        elif time_stop_flag:
            management_action = "time_stop"
        else:
            management_action = "hold"

        result = dict(pos)
        result.update({
            "current_confidence": round(current_confidence, 2),
            "confidence_drop": round(confidence_drop, 2),
            "early_exit_flag": early_exit_flag,
            "time_stop_flag": time_stop_flag,
            "trailing_stop_current": round(trailing_stop_current, 4),
            "days_held": days_held,
            "pnl_pct_of_target": round(pnl_pct_of_target, 4),
            "management_action": management_action,
            "highest_close_since_entry": round(highest, 4),
            "lowest_close_since_entry": round(lowest, 4),
        })
        results.append(result)

    return results


def _days_held(position: dict) -> int:
    """Calendar days since opened_at_utc. Returns 0 if unparseable/missing."""
    opened_at = str(position.get("opened_at_utc", ""))
    if len(opened_at) < 10:
        return 0
    try:
        opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - opened).days)
    except ValueError:
        return 0


def check_time_stop(
    position: dict,
    pnl_pct_of_target: float,
    day: int,
    time_stop_day: int = 10,
    min_progress_pct: float = 0.30,
) -> bool:
    """
    Return True if time stop should trigger.
    Trigger: day >= time_stop_day AND pnl_pct_of_target < min_progress_pct.
    """
    return day >= time_stop_day and pnl_pct_of_target < min_progress_pct


def compute_pnl_pct_of_target(
    current_price: float,
    entry_price: float,
    target_price: float,
    direction: str,
) -> float:
    """
    What % of the target profit has been achieved?
    Returns 0.0 if no progress, 1.0 if target hit, negative if loss.
    """
    if direction == "bullish":
        price_move = current_price - entry_price
        target_move = target_price - entry_price
    else:
        price_move = entry_price - current_price
        target_move = entry_price - target_price

    if target_move <= 0:
        return 0.0
    return price_move / target_move
