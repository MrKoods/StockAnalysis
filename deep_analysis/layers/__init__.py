"""
Per-layer deep analysis for V3.

Each `analyze_*` function takes a ticker (plus whatever context it needs) and
returns a rich structured view of what that layer sees — far more than the V2
0-N score, which is built for ranking, not explaining. Common return shape:

    {
        "summary":       {...},   # the handful of headline numbers
        "detail":        {...},   # the full breakdown
        "observations":  [str],   # plain-language factual statements, ready for
                                  # the synthesis prompt to weave in (facts, not
                                  # opinions — "RSI(14) is 74, top decile of the
                                  # last year", not "the stock is overbought")
        "data_quality":  "complete" | "partial" | "unavailable",
    }

These reuse V2's data clients and indicator primitives; they add assembly and
interpretation, not new feeds. Data sourcing for a commercial offering is still
unresolved (see CHANGELOG v3.0.0 / memory).
"""

from deep_analysis.layers.fundamental import analyze_fundamental
from deep_analysis.layers.macro import analyze_macro
from deep_analysis.layers.news import analyze_news
from deep_analysis.layers.positioning import analyze_positioning
from deep_analysis.layers.sentiment import analyze_sentiment
from deep_analysis.layers.technical import analyze_technical

__all__ = [
    "analyze_technical",
    "analyze_fundamental",
    "analyze_sentiment",
    "analyze_news",
    "analyze_positioning",
    "analyze_macro",
]
