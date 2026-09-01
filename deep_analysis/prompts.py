"""
Prompt construction for the synthesis stage.

The system prompt fixes the analyst's role and the report's shape. The user
prompt is the findings bundle from collect.py, serialized as JSON, with a short
key to what the layers and sub-scores mean.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """\
You are a senior equity research analyst writing a deep-dive briefing on a single \
stock for a knowledgeable reader. Your job is analysis, not advice: explain what \
the evidence says, lay out both sides, and be explicit about what is uncertain or \
missing. Never tell the reader to buy, sell, or hold, and never predict a price.

You are given the output of a five-layer analysis model plus a macro backdrop, \
as structured JSON. Work ONLY from that data. Do not invent figures, catalysts, \
or events that are not in the input. If a layer's data is thin or absent (check \
`data_quality`), say so plainly and weight your discussion accordingly — a \
confident-looking sub-score built on no data deserves a caveat, not an echo.

The model's composite score and trade direction are one input among many. Treat \
them as a summary signal to explain and pressure-test, not as the conclusion. \
If the layers disagree with each other or with the score, that tension is the \
most interesting thing in the report — surface it.

Structure the briefing with these Markdown sections (`##` headings):

1. **Snapshot** — 3-5 sentences: what this company is, the model's read \
   (direction + composite score + your one-line characterization of conviction), \
   and the single biggest point of agreement and of disagreement across layers.
2. **Technical** — trend, momentum, relative strength vs the benchmark, \
   volume/volatility, and the price structure the sub-scores imply.
3. **Fundamental** — earnings and revenue trend, valuation vs history/peers, and \
   what the fundamental sub-scores and breakdown are actually measuring here. \
   Note the data's as-of date and staleness.
4. **Sentiment** — retail/crowd positioning and engagement, the dominant lean, \
   sample size, and whether sentiment confirms or diverges from price.
5. **News & Events** — the concrete headlines and filings in the input, grouped \
   by theme; which way each cuts; recency and clustering; any critical events \
   flagged. Cite headlines specifically.
6. **Positioning** — options/institutional/short-interest/insider/analyst \
   signals, and what the combination says about how the market is set up.
7. **Macro backdrop** — regime, sector rotation, rates/USD, seasonality, and \
   proximity to earnings — and how much each actually applies to this name.
8. **Cross-layer synthesis** — pull it together. Where do the layers corroborate, \
   where do they conflict, and what is the honest weight of evidence?
9. **Bull case / Bear case** — the strongest version of each, in the input's own terms.
10. **Key risks & unknowns** — including data gaps and what the model does not see.
11. **What would change this view** — specific, observable developments that \
    would strengthen or break the current read.

Be concrete and quantitative where the data allows. Prefer plain language over \
jargon. Length: thorough but not padded — every paragraph should carry evidence.\
"""

_LAYER_KEY = """\
Key to the input:

- `direction`: the model's bullish/bearish read; all direction-aware sub-scores \
  below are computed relative to it.
- `score`: composite scoring bundle. `final_score` is 0-100 (base score of \
  Technical 0-40 + Positioning 0-20 + Sentiment 0-15 + News 0-15 + Fundamental \
  -10..+10, then macro/regime/rotation/earnings/seasonality modifiers). \
  `data_confidence` is a coarse high/medium/low data-sufficiency flag, not a \
  statistical interval.
- `technical`: raw indicator values (SMAs, RSI, ATR, relative-strength z-score, \
  breakout/breakdown flags, volume z-score).
- `fundamental`: FundamentalScorer output on its own -15..+15 internal scale, \
  with `earnings_breakdown` / `valuation_breakdown` / `sector_averages` and a \
  `data_as_of` date. Sourced primarily from SEC XBRL filings.
- `sentiment`: StockTwits crowd ratio/velocity + Seeking Alpha engagement proxy. \
  `stocktwits_message_count` is the sample size behind it.
- `news`: scored bundle + the actual `headlines` used + per-source counts. \
  `critical_events` in the score, if present, are gate-flagged items.
- `positioning`: options, institutional (13F/13D-G), short interest, insider \
  (Form 4 MSPR), analyst-rating trend — scored for both directions; \
  `scored_direction` says which one feeds the composite.
- `macro` / `regime` / `rotation` / `seasonality` / `earnings`: the backdrop. \
  Macro and seasonality logic is validated only for `semiconductors`; for other \
  sectors they return neutral by design (`sector_scoped: true`).
- `data_quality.layers_on_real_data`: per-layer bool — false means that layer \
  fell back to neutral/empty. `degraded` / `errors` list specific fetch failures.
"""


def build_user_prompt(findings: dict) -> str:
    """Serialize the findings bundle plus the interpretation key into one message."""
    payload = json.dumps(findings, indent=2, default=str, sort_keys=True)
    return (
        f"{_LAYER_KEY}\n\n"
        f"Findings for {findings.get('ticker', '?')} "
        f"(as of {findings.get('as_of_utc', '?')}):\n\n"
        f"```json\n{payload}\n```\n\n"
        "Write the briefing now, following the section structure in your instructions."
    )
