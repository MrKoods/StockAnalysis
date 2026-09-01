"""
Stage 3 — assemble the final Markdown deliverable: a header, the model's
briefing, a quantitative appendix (the score rail the narrative sits on), the
data-quality report, and a disclaimer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

DISCLAIMER = (
    "This briefing is automated research for informational and educational purposes only. "
    "It is not investment advice, not a recommendation to buy, sell, or hold any security, "
    "and not a forecast. It is generated from third-party data that may be incomplete, "
    "delayed, or wrong. Do your own research and consult a licensed professional before "
    "making any investment decision."
)


def _fmt(value, nd: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{nd}f}"
    return str(value)


def _score_table(score: dict) -> str:
    if not score:
        return "_Composite score unavailable — see data-quality notes._"
    rows = [
        ("Direction", score.get("direction", "—")),
        ("Final score", f"{_fmt(score.get('final_score'))} / 100"),
        ("Base score", _fmt(score.get("base_score"))),
        ("· Technical", f"{_fmt(score.get('technical_total'))} / {_fmt(score.get('technical_max'))}"),
        ("· Positioning", f"{_fmt(score.get('positioning_total'))} / 20"),
        ("· Sentiment", f"{_fmt(score.get('sentiment_total'))} / {_fmt(score.get('sentiment_max'))}"),
        ("· News", f"{_fmt(score.get('news_total'))} / {_fmt(score.get('news_max'))}"),
        ("· Fundamental", _fmt(score.get("fundamental_score"))),
        ("Total modifiers", _fmt(score.get("total_modifier"))),
        ("· Regime", _fmt(score.get("regime_modifier"))),
        ("· Sector rotation", _fmt(score.get("sector_rotation_modifier"))),
        ("· Earnings", _fmt(score.get("earnings_modifier"))),
        ("· Seasonality", _fmt(score.get("seasonality_modifier"))),
        ("· Macro", _fmt(score.get("macro_modifier"))),
        ("Data confidence", score.get("data_confidence", "—")),
        ("Degraded sub-signals", f"{score.get('degraded_sub_signal_count', '—')} / {score.get('total_sub_signals_checked', '—')}"),
    ]
    lines = ["| Metric | Value |", "| --- | --- |"]
    lines += [f"| {name} | {val} |" for name, val in rows]
    return "\n".join(lines)


def _data_quality_block(dq: dict) -> str:
    layers = dq.get("layers_on_real_data", {})
    lines = ["| Layer | On real data |", "| --- | --- |"]
    lines += [f"| {name} | {'yes' if ok else 'no'} |" for name, ok in layers.items()]
    out = ["\n".join(lines)]
    for label, key in (("Degraded fetches", "degraded"), ("Errors", "errors")):
        items = dq.get(key) or []
        if items:
            out.append(f"\n**{label}:**\n" + "\n".join(f"- {i}" for i in items))
    return "\n".join(out)


def render_report(
    findings: dict,
    synthesis: Optional[dict] = None,
    *,
    model_version: str = "v3.0.0",
) -> str:
    """
    Combine a findings bundle and (optionally) a synthesis result into the final
    Markdown document. With `synthesis=None`, renders the header + appendices
    only — useful for inspecting the data before spending a model call.
    """
    ticker = findings.get("ticker", "?")
    as_of = findings.get("as_of_utc", datetime.now(timezone.utc).isoformat())
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        f"# {ticker} — Deep Analysis",
        "",
        f"*Five-layer research briefing · model {model_version} · generated {generated}*",
        "",
        f"- **Ticker:** {ticker}",
        f"- **Sector / benchmark:** {findings.get('sector') or '—'} / {findings.get('benchmark') or '—'}",
        f"- **Model read:** {findings.get('direction', '—')}, "
        f"composite {_fmt((findings.get('score') or {}).get('final_score'))}/100",
        f"- **Data as of:** {as_of}",
        "",
        "---",
        "",
    ]

    if synthesis and synthesis.get("report_markdown"):
        parts.append(synthesis["report_markdown"].strip())
        parts.append("")
        usage = synthesis.get("usage") or {}
        parts.append(
            f"<sub>Synthesis: {synthesis.get('model', '—')} · "
            f"in {usage.get('input_tokens', '—')} tok / out {usage.get('output_tokens', '—')} tok</sub>"
        )
    else:
        parts.append("_Synthesis not run — quantitative snapshot only._")

    parts += [
        "",
        "---",
        "",
        "## Appendix A — Quantitative snapshot",
        "",
        _score_table(findings.get("score") or {}),
        "",
        "## Appendix B — Data quality",
        "",
        _data_quality_block(findings.get("data_quality") or {}),
        "",
        "---",
        "",
        f"_{DISCLAIMER}_",
        "",
    ]
    return "\n".join(parts)
