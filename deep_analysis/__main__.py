"""
CLI: run the deep-analysis pipeline for one ticker.

    python -m deep_analysis NVDA
    python -m deep_analysis KEY --benchmark KRE --sector regional_banks -o key.md
    python -m deep_analysis NVDA --findings-only        # skip the model call
    python -m deep_analysis NVDA --dump-findings nvda.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from deep_analysis.collect import collect_findings
from deep_analysis.render import render_report
from deep_analysis.synthesize import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    SynthesisError,
    synthesize,
)


def _model_version() -> str:
    try:
        for line in Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("## [v"):
                return line.split("[", 1)[1].split("]")[0]
    except Exception:  # noqa: BLE001
        pass
    return "v3.0.0"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="deep_analysis", description="Five-layer deep analysis for one ticker.")
    parser.add_argument("ticker", help="Ticker symbol, e.g. NVDA")
    parser.add_argument("--benchmark", help="Relative-strength benchmark (default: ticker's sector benchmark, else SMH)")
    parser.add_argument("--sector", help="Sector key for sector-scoped modifiers (default: ticker's configured sector)")
    parser.add_argument("--scan-type", default="post_close", choices=["pre_market", "mid_session", "post_close"])
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Anthropic model (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("-o", "--out", type=Path, help="Write the Markdown report here (default: stdout)")
    parser.add_argument("--findings-only", action="store_true", help="Skip the model call; render the quantitative snapshot only")
    parser.add_argument("--dump-findings", type=Path, help="Also write the raw findings bundle as JSON here")
    args = parser.parse_args(argv)

    findings = collect_findings(
        args.ticker,
        benchmark=args.benchmark,
        sector=args.sector,
        scan_type=args.scan_type,
    )

    if args.dump_findings:
        args.dump_findings.write_text(json.dumps(findings, indent=2, default=str), encoding="utf-8")
        print(f"findings written to {args.dump_findings}", file=sys.stderr)

    synthesis = None
    if not args.findings_only:
        try:
            synthesis = synthesize(findings, model=args.model, effort=args.effort)
        except SynthesisError as exc:
            print(f"synthesis failed: {exc}", file=sys.stderr)
            print("rendering the quantitative snapshot only.", file=sys.stderr)

    report = render_report(findings, synthesis, model_version=_model_version())

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"report written to {args.out}", file=sys.stderr)
    else:
        print(report)

    return 0 if (args.findings_only or synthesis) else 1


if __name__ == "__main__":
    raise SystemExit(main())
