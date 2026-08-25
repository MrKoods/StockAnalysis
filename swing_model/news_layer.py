"""
NER-extracted ticker-specific news sentiment; source credibility weighting;
narrative theme tracking; news clustering; timezone-adjusted windows.
Output used by scoring.py for the News component (max 15 points).
"""

import re
from datetime import datetime, timezone
from typing import Optional

from shared.utils.source_credibility import score_news_outlet
from shared.utils.ner_extractor import extract_ticker_sentiments, is_ticker_relevant
from shared.utils.narrative_tracker import identify_dominant_theme, theme_alignment_modifier
from shared.utils.temporal_alignment import news_decay_weight
from shared.utils.event_gate import (
    classify_severity as _classify_event_severity,
    SEVERITY_CRITICAL, SCOPE_TICKER, SCOPE_SECTOR,
)
from shared.utils.data_validator import validate_news_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)



def classify_severity(item: dict, cfg: Optional[dict] = None, sector: Optional[str] = None) -> dict:
    """
    Classify one processed news item's Event Severity Gate status using the
    config-driven keyword + source rules in config/swing_config.yaml
    (event_severity_gate). Returns a copy of `item` with 'severity' ("normal"
    or "critical") and 'scope' ("ticker" | "sector" | None) attached.

    `sector`: restricts sector-wide trigger matching to this sector's keyword
    list (see event_gate.classify_severity) — the ticker being scored belongs
    to this sector, so a different sector's trigger words shouldn't fire here.

    This is an advisory classification, not a scoring input — News keeps its
    normal 15-point additive scoring for every item regardless of severity.
    """
    cfg = cfg or {}
    headline = item.get("title", "") or item.get("headline", "")
    source = item.get("source_domain", "") or item.get("publisher", "") or item.get("source", "")
    result = _classify_event_severity(headline, source, cfg, sector=sector)

    updated = dict(item)
    updated["severity"] = result["severity"]
    updated["scope"] = result["scope"]
    updated["trigger_match"] = result["trigger_match"]
    return updated


def free_sources_flag_critical_event(
    free_source_articles: list[dict],
    ticker: str,
    cfg: Optional[dict] = None,
    sector: Optional[str] = None,
) -> bool:
    """
    Cheap, local (no API cost) check for whether any already-fetched
    Yahoo/Finnhub/Seeking Alpha headline classifies as a critical event for
    `ticker` — used by run_swing_model.py/paper_runner.py to decide whether a
    scan should spend one Alpha Vantage call to cross-reference the event
    with an independent source. AV is a confirmation tool, not a routine
    per-ticker news source: every scan (pre-market, mid-session, post-close
    alike) fetches the three free sources first and only calls AV when one of
    them already flagged something critical, instead of spending a budgeted
    call on every ticker every day regardless of whether anything happened.

    Same classify_severity() rules compute_news_score() already applies to
    every article — this just runs them standalone, before AV is fetched,
    so the fetch decision can depend on the result. Not a scoring input.
    """
    cfg = cfg or {}
    for art in free_source_articles or []:
        title = art.get("title", "")
        source = art.get("source_domain", "") or art.get("source", "")
        classified = classify_severity({"title": title, "source_domain": source}, cfg, sector=sector)
        if classified["severity"] != SEVERITY_CRITICAL:
            continue
        if classified["scope"] == SCOPE_SECTOR:
            return True
        if classified["scope"] == SCOPE_TICKER and is_ticker_relevant(title, ticker):
            return True
    return False


def _normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — so the same wire
    story syndicated with minor punctuation/casing differences across feeds
    still hashes to the same dedup key."""
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _dedupe_articles(articles: list[dict]) -> list[dict]:
    """
    Collapse the same underlying story pulled from multiple feeds (AV, Yahoo,
    Finnhub, Seeking Alpha, SEC EDGAR) down to one record. Confirmed live:
    count_independent_cluster's own dedup keys on source_domain, but
    news_client.py hardcodes "finance.yahoo.com" for every Yahoo item
    regardless of the real publisher — so one Reuters wire story pulled via
    AV, Yahoo, and Finnhub simultaneously registered as 3 "independent"
    sources, inflating both relevant_article_count and clustering_score for a
    single piece of information. No dedup existed before this at all: this
    function runs once, upstream of every other article-count-based signal.
    Keeps the copy with the highest source credibility per duplicate group
    (first-seen breaks ties) so downstream scoring credits the most credible
    version of the story.
    """
    best_by_key: dict[str, tuple[float, dict]] = {}
    for art in articles:
        title = art.get("title", "") or art.get("headline", "")
        key = _normalize_title(title)
        if not key:
            continue
        cred = score_news_outlet(art.get("source_domain", "") or art.get("publisher", ""))
        existing = best_by_key.get(key)
        if existing is None or cred > existing[0]:
            best_by_key[key] = (cred, art)
    return [art for _, art in best_by_key.values()]


def compute_news_score(
    alpha_vantage_articles: list[dict],
    yahoo_articles: list[dict],
    ticker: str,
    cfg: Optional[dict] = None,
    reference_date: Optional[datetime] = None,
    finnhub_articles: Optional[list[dict]] = None,
    sector: Optional[str] = None,
    seeking_alpha_articles: Optional[list[dict]] = None,
    sec_edgar_filings: Optional[list[dict]] = None,
    direction: str = "bullish",
) -> dict:
    """
    Compute the full news score bundle for a ticker.

    Scoring spec (sum = 15):
    - credibility_weighted_score:  0-6
    - theme_alignment_score:       0-4
    - clustering_score:            0-3
    - decay_score:                 0-2

    direction: the candidate's real trade direction ("bullish"/"bearish"),
    pre-determined by the caller (scoring.py::determine_direction(), hoisted
    early in run_swing_model.py/paper_runner.py — see those files). Used for
    theme_alignment_score (a theme that opposes the candidate's own direction
    now scores low instead of high — see theme_alignment_modifier) and for
    credibility_weighted_score (bearish-confirming articles score high for a
    bearish candidate instead of bullish-confirming ones). Previously
    theme_alignment_score re-derived its own local direction estimate from
    this same scan's NER bull/bear tag counts — replaced by the real,
    independently-determined direction now that the pipeline computes one
    before this function runs, removing a circular "the news infers its own
    direction from itself" estimate in favor of the model's actual thesis.

    `sector`: which sector `ticker` belongs to (config/swing_config.yaml's
    watchlist.sectors) — restricts Event Severity Gate sector-wide trigger
    matching to that sector's keyword list, so a chip-ban headline doesn't
    flag a critical event while scoring a bank ticker and vice versa. NER
    ticker-mention matching below is intentionally NOT sector-scoped — a
    headline can legitimately mention any active ticker in any sector.

    `seeking_alpha_articles`: Seeking Alpha editorial items (already fetched
    every scan for the Sentiment layer's engagement-velocity proxy, at no
    extra API cost). Folded directly into the scored News total (credibility/
    theme/clustering/decay) as of the AV-budget-relief change below — source
    credibility for "seekingalpha.com" (0.55) already existed in
    shared/utils/source_credibility.py before this change ever wired it in.
    Also still covers Event Severity Gate detection on every scan: back when
    AV news was restricted to the post-close scan for budget reasons,
    pre-market/mid-session couldn't detect a critical event until hours after
    it broke (observed: a real headline sat undetected ~13 hours before the
    post-close scan finally caught it) — Seeking Alpha running on every scan
    closed that gap, and now (see free_sources_flag_critical_event()) also
    drives whether AV gets called at all, on every scan type alike.

    NOT modeled in the backtest: no historical Seeking Alpha article archive
    exists (unlike AV, whose historical articles are cached from Q4 2025
    onward — see backtesting/historical_news_loader.py), so
    backtesting/simulation.py always passes seeking_alpha_articles=None. This
    is the same "accumulates going forward, not backtestable yet" caveat
    already accepted for Positioning and live StockTwits sentiment — track it
    the same way, don't treat backtest parity as a blocker for this change.
    Same caveat applies to sec_edgar_filings below — no historical 8-K archive
    is cached, so backtesting always passes None for it too.

    `sec_edgar_filings`: recent 8-K filings for `ticker` from SEC EDGAR (see
    shared/api_clients/sec_edgar_client.py) — a company's own regulatory
    disclosure, scored at the highest source credibility (1.0) since it's a
    primary source, not third-party reporting. Folded into the same scored
    total and Event Severity Gate classification as every other source.

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}

    now = reference_date if reference_date is not None else datetime.now(timezone.utc)
    from shared.utils.sector_config import get_all_tickers
    watchlist = get_all_tickers(cfg)

    # Tier B batch 2 (2026-08-19): decay params now read from config.
    news_cfg = cfg.get("news", {})
    decay_halflife_hours = float(news_cfg.get("decay_halflife_hours", 24.0))
    decay_zero_at_days = float(news_cfg.get("decay_zero_at_days", 5.0))

    all_articles = _dedupe_articles(
        list(alpha_vantage_articles) + list(yahoo_articles) + list(finnhub_articles or [])
        + list(seeking_alpha_articles or []) + list(sec_edgar_filings or [])
    )

    # Log-only visibility, not a hard gate — an out-of-range sentiment score
    # or future-dated article previously flowed straight into scoring with
    # no logged trace at all (Signal Integrity Audit finding E.1).
    _news_valid, _news_failures = validate_news_data(ticker, all_articles)
    if not _news_valid:
        logger.warning(f"{ticker}: Phase 9 news validation flagged {_news_failures}")

    # ---------------------------------------------------------------------------
    # Filter to relevant articles only (NER confirms ticker mention)
    # ---------------------------------------------------------------------------
    relevant = []
    ner_results = []
    for art in all_articles:
        title = art.get("title", "")
        if is_ticker_relevant(title, ticker):
            ts = _parse_ts(art.get("timestamp_utc", ""))
            decay = news_decay_weight(ts, now_utc=now, halflife_hours=decay_halflife_hours, zero_at_days=decay_zero_at_days)
            if decay <= 0.0:
                continue  # Too old

            ner = extract_ticker_sentiments(title, watchlist)
            ticker_sentiment = ner.get(ticker)
            outlet_cred = score_news_outlet(art.get("source_domain", "") or art.get("publisher", ""))

            article_record = {
                **art,
                "_ts": ts,
                "_decay": decay,
                "_credibility": outlet_cred,
                "_ner_sentiment": ticker_sentiment,
            }
            relevant.append(article_record)
            ner_results.append({"ticker": ticker, "sentiment": ticker_sentiment, "title": title})

    # ---------------------------------------------------------------------------
    # Event Severity Gate — classify every processed item for severity/scope.
    # Sector-wide triggers (export policy, tariffs, Taiwan Strait, etc.) are
    # checked across ALL articles, since a macro headline may never name a
    # specific ticker and so wouldn't pass the ticker-relevance filter above —
    # but still subject to the same recency bar as ticker-relevant articles
    # below, so a stale article the news API keeps resurfacing (observed in
    # practice: the same 6-day-old headline re-triggering a fresh block every
    # day after the prior one expired) stops counting as a new critical event.
    # Ticker triggers require NER attribution to this ticker, so they're only
    # checked against articles already confirmed relevant (NER already ran).
    # This is classification only — no scoring effect here; the caller
    # (run_swing_model.py) decides whether a critical event blocks or is
    # merely logged, using scoring.py's computed trade direction.
    # ---------------------------------------------------------------------------
    critical_events = []
    for art in all_articles:
        title = art.get("title", "")
        source = art.get("source_domain", "") or art.get("publisher", "") or art.get("source", "")
        ts = _parse_ts(art.get("timestamp_utc", ""))
        decay = news_decay_weight(ts, now_utc=now, halflife_hours=decay_halflife_hours, zero_at_days=decay_zero_at_days)
        if decay <= 0.0:
            continue  # Too old — same recency bar as ticker-relevant articles below
        classified = classify_severity({"title": title, "source_domain": source}, cfg, sector=sector)
        if classified["severity"] == SEVERITY_CRITICAL and classified["scope"] == SCOPE_SECTOR:
            critical_events.append({
                "headline": title,
                "source": source,
                "scope": SCOPE_SECTOR,
                "trigger_match": classified["trigger_match"],
                "ner_sentiment": None,
                "event_timestamp_utc": ts.isoformat(),
            })

    for art in relevant:
        title = art.get("title", "")
        source = art.get("source_domain", "") or art.get("publisher", "") or art.get("source", "")
        classified = classify_severity({"title": title, "source_domain": source}, cfg, sector=sector)
        if classified["severity"] == SEVERITY_CRITICAL and classified["scope"] == SCOPE_TICKER:
            critical_events.append({
                "headline": title,
                "source": source,
                "scope": SCOPE_TICKER,
                "trigger_match": classified["trigger_match"],
                "ner_sentiment": art.get("_ner_sentiment"),
                "event_timestamp_utc": art["_ts"].isoformat(),
            })

    # ---------------------------------------------------------------------------
    # 1. Credibility-weighted score (0-6)
    # ---------------------------------------------------------------------------
    credibility_weighted_score = _score_credibility_weighted(relevant, ticker, direction=direction)

    # ---------------------------------------------------------------------------
    # 2. Theme alignment score (0-4)
    # ---------------------------------------------------------------------------
    # identify_dominant_theme's momentum calc assumes texts[0] is the OLDEST
    # article (it compares the first half to the second half) — `relevant`
    # is built by concatenating Alpha Vantage + Yahoo + Finnhub + Seeking
    # Alpha + SEC EDGAR articles one source at a time, never sorted by time,
    # so index order reflected source order, not real chronology. A
    # genuinely newest-and-rising theme could register as "declining" purely
    # because of which source happened to come first in the concatenation.
    texts = [art.get("title", "") for art in sorted(relevant, key=lambda a: a["_ts"])]
    theme_result = identify_dominant_theme(texts, ticker)
    dominant_theme = theme_result["dominant_theme"]

    alignment_val = theme_alignment_modifier(dominant_theme, direction, ticker)
    # alignment_val in [-1, +1]; scale to [0, 4]. Zero when no theme / no articles.
    if dominant_theme == "none" or not relevant:
        theme_alignment_score = 0.0
    else:
        theme_alignment_score = min(4.0, max(0.0, (alignment_val + 1.0) * 2.0))

    # ---------------------------------------------------------------------------
    # 3. Clustering score (0-3)
    # ---------------------------------------------------------------------------
    cluster_count = count_independent_cluster(
        relevant, ticker, window_days=int(news_cfg.get("cluster_window_days", 2)),
        reference_date=now, direction=direction
    )
    clustering_score = float(min(3, cluster_count))

    # ---------------------------------------------------------------------------
    # 4. Decay score (0-2): freshness of the MOST RECENT relevant article.
    #
    # Previously averaged _decay across every relevant article — but freshness
    # already acts as a per-article weight inside credibility_weighted_score
    # (w = cred * decay), so a batch of fresh, credible articles was rewarded
    # twice by the same underlying signal: once through a less-diluted
    # directional score, and again through this separate additive average of
    # the identical decay values. Using the single freshest article instead
    # answers a genuinely different question — "is something happening right
    # now" — rather than re-deriving the same per-article average baked into
    # credibility_weighted_score's own weighting.
    # ---------------------------------------------------------------------------
    if relevant:
        most_recent_decay = max(art["_decay"] for art in relevant)
        decay_score = round(most_recent_decay * 2.0, 2)
    else:
        decay_score = 0.0

    news_score_total = credibility_weighted_score + theme_alignment_score + clustering_score + decay_score

    return {
        # Sub-scores
        "credibility_weighted_score": round(credibility_weighted_score, 2),
        "theme_alignment_score": round(theme_alignment_score, 2),
        "clustering_score": round(clustering_score, 2),
        "decay_score": round(decay_score, 2),
        "news_score_total": round(min(15.0, news_score_total), 2),

        # Metadata
        "news_decay_weighted_score": round(credibility_weighted_score, 2),
        "dominant_narrative_theme": dominant_theme,
        "theme_momentum": theme_result.get("theme_momentum", "stable"),
        "news_cluster_count": cluster_count,
        "source_credibility_weighted_score": round(credibility_weighted_score, 2),
        "ner_sentiment_per_article": ner_results,
        "relevant_article_count": len(relevant),
        "total_article_count": len(all_articles),

        # Event Severity Gate — classification only; run_swing_model.py decides
        # whether to block (thesis-opposed) or merely log (thesis-aligned/neutral).
        "critical_events": critical_events,
    }


def score_news_credibility(
    articles: list[dict],
    ticker: str,
    direction: str = "bullish",
) -> float:
    """
    Compute credibility-weighted news sentiment score for a ticker (0-6).
    NER extracts ticker-specific sentiment from each article.
    Weight = source_credibility × decay_weight.
    """
    return _score_credibility_weighted(articles, ticker, direction=direction)


def count_independent_cluster(
    articles: list[dict],
    ticker: str,
    window_days: int = 2,
    reference_date: Optional[datetime] = None,
    direction: str = "bullish",
) -> int:
    """
    Count independent, direction-CONFIRMING news articles in window_days
    (cap at 3). Independence requires: different source_domain.

    direction: which count to return — bull_count for a bullish candidate,
    bear_count for a bearish one. Previously returned max(bull_count,
    bear_count) regardless of direction, so a bearish candidate could score
    full clustering points off a cluster of bullish-leaning articles that
    actually oppose its thesis (Signal Integrity Audit finding B.4) — the
    same "confirming vs. opposing" mirroring
    _score_credibility_weighted/theme_alignment_modifier already apply.
    """
    if not articles:
        return 0

    now = reference_date if reference_date is not None else datetime.now(timezone.utc)
    from datetime import timedelta
    cutoff = now - timedelta(days=window_days)

    seen_domains = set()
    directions = []

    for art in articles:
        ts = art.get("_ts") or _parse_ts(art.get("timestamp_utc", ""))
        if ts < cutoff:
            continue
        domain = art.get("source_domain", "") or art.get("publisher", "unknown")
        sentiment = art.get("_ner_sentiment") or art.get("overall_sentiment_label", "Neutral")

        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        normalized = sentiment.lower() if isinstance(sentiment, str) else "neutral"
        if normalized in ("bullish", "positive", "somewhat-bullish"):
            directions.append("bullish")
        elif normalized in ("bearish", "negative", "somewhat-bearish"):
            directions.append("bearish")

    if not directions:
        return 0

    bull_count = directions.count("bullish")
    bear_count = directions.count("bearish")
    confirming_count = bear_count if direction == "bearish" else bull_count
    return min(3, confirming_count)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_credibility_weighted(articles: list[dict], ticker: str, direction: str = "bullish") -> float:
    """
    Credibility × decay weighted sentiment → scaled to [0, 6].
    Neutral articles score at 0.5 weight (halfway contribution).

    direction="bearish": flips which polarity is "confirming" — bearish
    articles score 1.0 and bullish articles score 0.0, the mirror image of
    the bullish default, matching narrative_tracker.theme_alignment_modifier's
    existing symmetric pattern.
    """
    if not articles:
        return 0.0

    confirming, opposing = ("bearish", "bullish") if direction == "bearish" else ("bullish", "bearish")
    weighted_sum = 0.0
    total_weight = 0.0

    for art in articles:
        cred = art.get("_credibility")
        if cred is None:
            cred = score_news_outlet(art.get("source_domain", "") or art.get("publisher", ""))
        decay = art.get("_decay", 1.0)
        w = cred * decay

        sentiment = art.get("_ner_sentiment") or art.get("overall_sentiment_label", "Neutral")
        normalized = str(sentiment).lower()
        if normalized in ("bullish", "positive", "somewhat-bullish"):
            polarity = "bullish"
        elif normalized in ("bearish", "negative", "somewhat-bearish"):
            polarity = "bearish"
        else:
            polarity = None

        if polarity == confirming:
            sentiment_val = 1.0
        elif polarity == opposing:
            sentiment_val = 0.0
        else:
            sentiment_val = 0.5

        weighted_sum += w * sentiment_val
        total_weight += w

    if total_weight == 0:
        return 0.0

    # weighted_avg in [0, 1]; scale to [0, 6]
    weighted_avg = weighted_sum / total_weight
    return round(weighted_avg * 6.0, 2)


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to UTC datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)
