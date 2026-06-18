import csv
import json
from datetime import datetime
from pathlib import Path

import yaml

from shared.utils.logger import get_logger
from swing_model.indicator_pipeline import SwingIndicatorPipeline
from swing_model.scoring import SwingScorer
from swing_model.trade_selector import SwingTradeSelector

logger = get_logger(__name__)


def _load_configs() -> tuple[dict, dict]:
    with open("config/swing_config.yaml") as f:
        swing = yaml.safe_load(f)
    with open("config/global_config.yaml") as f:
        global_ = yaml.safe_load(f)
    return swing, global_


def main():
    """Load config, run the full swing pipeline, and write ranked recommendations to output."""
    swing_config, global_config = _load_configs()

    output_dir = Path(global_config["output"]["swing_output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = SwingIndicatorPipeline(swing_config, global_config)
    scorer = SwingScorer(swing_config)
    selector = SwingTradeSelector(swing_config)

    logger.info("Running swing indicator pipeline...")
    indicators_list = pipeline.run()

    recommendations = []
    for ticker_data in indicators_list:
        ticker = ticker_data["ticker"]
        score = scorer.score(ticker_data)
        rec = selector.select(ticker, score, ticker_data)
        if rec:
            recommendations.append(rec)

    # Rank by absolute score descending (highest conviction first)
    recommendations.sort(key=lambda r: abs(r["score"]), reverse=True)

    today = datetime.today().strftime("%Y-%m-%d")
    fmt = global_config["output"]["format"]

    if fmt == "json":
        out_path = output_dir / f"swing_recommendations_{today}.json"
        with open(out_path, "w") as f:
            json.dump(recommendations, f, indent=2)
    else:
        out_path = output_dir / f"swing_recommendations_{today}.csv"
        if recommendations:
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=recommendations[0].keys())
                writer.writeheader()
                writer.writerows(recommendations)
        else:
            out_path.touch()

    logger.info(f"Wrote {len(recommendations)} recommendation(s) to {out_path}")

    _print_summary(recommendations, today)


def _print_summary(recommendations: list[dict], today: str) -> None:
    print(f"\n=== Swing Model Recommendations  {today} ===")
    if not recommendations:
        print("  No candidates above minimum R:R threshold today.")
        return
    header = f"  {'Ticker':<6}  {'Dir':<8}  {'Score':>5}  {'Structure':<25}  {'Entry':>7}  {'Stop':>7}  {'Target':>8}  {'R:R':>4}  {'IV':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in recommendations:
        print(
            f"  {r['ticker']:<6}  {r['direction']:<8}  {r['score']:>+5}  "
            f"{r['structure']:<25}  {r['entry']:>7.2f}  {r['stop']:>7.2f}  "
            f"{r['target']:>8.2f}  {r['rr_ratio']:>4.1f}  {r['iv_regime']:>6}"
        )


if __name__ == "__main__":
    main()
