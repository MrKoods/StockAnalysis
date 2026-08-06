"""
Generates data/processed/win_probability_calibration.json from real backtest
replay — the calibration curve win_probability_calibration.py's
calibrate_win_probability() applies in place of trade_selector.py's old
`win_prob = confidence / 100.0`.

Pools qualifying-trade outcomes across all three traded sectors (same pooling
backtest_engine.run_multi_sector_backtest already does), then sweeps a fine
confidence-threshold grid via run_sensitivity_analysis to get a real
(threshold -> historical win rate) reading at each point, isotonic-smoothed
into a proper non-decreasing calibration curve.

Usage: python -m backtesting.fit_win_probability_calibration
"""

from datetime import datetime, timezone

from backtesting.backtest_engine import _get_test_outcomes, _SECTOR_DATASETS
from backtesting.metrics import run_sensitivity_analysis
from backtesting.run_backtest import load_historical_data
from shared.utils.logger import get_logger
from swing_model.win_probability_calibration import fit_calibration_curve, save_calibration

logger = get_logger(__name__)

_THRESHOLD_GRID = list(range(40, 100, 5))


def collect_pooled_outcomes(config_path: str = "config/swing_config.yaml") -> tuple[list[dict], dict]:
    """
    Loads every sector's historical dataset and pools their out-of-sample
    outcome sets — mirrors run_multi_sector_backtest's own pooling, but
    returns the raw unfiltered outcomes (every simulated signal, not just
    qualifying ones) since the whole point here is to sweep every threshold,
    not just the go-live one.

    Returns (pooled_outcomes, per_sector_counts).
    """
    pooled: list[dict] = []
    per_sector_counts: dict[str, int] = {}

    for sector, (data_dir, benchmark) in _SECTOR_DATASETS.items():
        historical_data = load_historical_data(data_dir)
        if not historical_data:
            logger.warning(f"{sector}: no historical data found in {data_dir}, skipping")
            continue
        outcomes, _months, _dates, _cutoff = _get_test_outcomes(
            historical_data, config_path, train_split=0.70, benchmark_ticker=benchmark,
        )
        per_sector_counts[sector] = len(outcomes)
        pooled.extend(outcomes)

    return pooled, per_sector_counts


def main() -> None:
    pooled_outcomes, per_sector_counts = collect_pooled_outcomes()
    if not pooled_outcomes:
        logger.error("No historical outcomes across any sector — cannot fit a calibration curve.")
        return

    logger.info(f"Pooled outcomes per sector: {per_sector_counts} (total {len(pooled_outcomes)})")

    sensitivity_df = run_sensitivity_analysis(pooled_outcomes, test_months=1.0, thresholds=_THRESHOLD_GRID)
    sensitivity_rows = sensitivity_df.to_dict("records")

    calibration_points = fit_calibration_curve(sensitivity_rows)
    if not calibration_points:
        logger.error("Every threshold in the sweep had zero qualifying trades — nothing to calibrate from.")
        return

    source = (
        f"backtesting.fit_win_probability_calibration, generated {datetime.now(timezone.utc).isoformat()}, "
        f"pooled sectors={list(per_sector_counts)}, per_sector_outcome_counts={per_sector_counts}, "
        f"threshold_grid={_THRESHOLD_GRID}"
    )
    save_calibration(calibration_points, source)

    print("\nWin probability calibration curve (isotonic-smoothed, pooled across sectors):\n")
    for point in calibration_points:
        print(f"  threshold={point['threshold']:>3}  win_rate={point['win_rate']:.4f}  n_trades={point['n_trades']}")
    print("\nSaved to data/processed/win_probability_calibration.json")


if __name__ == "__main__":
    main()
