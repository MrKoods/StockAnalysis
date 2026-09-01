"""
V3 — deep single-ticker analysis.

V2 (the `swing_model` package) scans a watchlist and ranks trade candidates.
V3 does the opposite job: take ONE ticker the caller already cares about, run
every analysis layer at full depth, and produce a written research briefing —
not a buy/sell call.

Two stages:
  1. collect.collect_findings(ticker)  — run the five layers + macro backdrop,
     gather every sub-signal and its raw inputs into one structured bundle.
  2. synthesize.synthesize(findings)   — hand that bundle to Claude and get back
     a layer-by-layer deep analysis with a cross-layer synthesis and bull/bear
     framing.

render.render_report() stitches the two together into the final Markdown
deliverable. `python -m deep_analysis NVDA` runs the whole pipeline.
"""

from deep_analysis.collect import collect_findings
from deep_analysis.render import render_report
from deep_analysis.synthesize import SynthesisError, synthesize

__all__ = ["collect_findings", "synthesize", "render_report", "SynthesisError"]
