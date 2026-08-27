"""
Statistical evaluation primitives — the part of the V2 codebase that survived
the V3 rebuild, because it is the part that was never the problem.

Everything here operates on plain numeric sequences or a pandas equity/returns
series. Nothing here knows what a "signal", a "score", or a "trade structure"
is. That decoupling is deliberate: in V2 these functions took V2's own
outcome-dict shape as input, which quietly made the measurement layer a
dependent of the strategy layer, and meant a change in scoring semantics could
alter what "win rate" meant without anything failing.

The three functions that exist specifically to stop this project fooling itself
again — and the incidents that produced them — are:

  benjamini_hochberg_correction   A single backtest run computes many
                                  correlations at once. In V2 (v2.2.96) one
                                  p=0.0501 reading out of ~15 was reported as a
                                  real finding; it did not survive correction
                                  (v2.2.97). Always correct across the batch.

  bootstrap_ic_ci                 A second, independent check on any IC point
                                  estimate. If the resampled interval straddles
                                  zero, the point estimate is not actionable
                                  regardless of its p-value.

  compute_deflated_sharpe_ratio   Trying N configurations and reporting the
                                  winner inflates Sharpe even when every
                                  configuration has zero true edge. Report the
                                  deflated number whenever a sweep preceded the
                                  headline figure.

See docs/v2_postmortem.md for the full trap list.
"""

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm, pearsonr, spearmanr

# --------------------------------------------------------------------------
# Predictive power
# --------------------------------------------------------------------------

def compute_information_coefficient(
    scores: Sequence[float],
    forward_returns: Sequence[float],
    method: str = "spearman",
) -> dict:
    """
    Rank correlation (Information Coefficient) between a score and the forward
    return realized after it.

    This is the primary V3 evidence metric, and it is deliberately computed on
    the FULL scored population rather than on a filtered subset of "qualifying"
    observations. V2's central failure mode was that its qualifying filter left
    10-28 trades across 13 years — far too few to say anything — while thousands
    of scored ticker-days sat discarded one line earlier. IC uses all of them.

    Known limitation, unchanged from V2 and still not solved: observations
    across ticker-days are not independent (same-name serial correlation,
    common-day market moves), so the p-value is optimistic versus a true i.i.d.
    sample. Treat it as directional. For a cross-sectional panel strategy the
    honest version is a per-date IC averaged across dates (see
    compute_cross_sectional_ic below), which sidesteps most of the common-day
    dependence.

    Returns {"ic", "p_value", "n", "method"}. ic/p_value are 0.0/1.0 when fewer
    than 3 valid pairs exist or either series is constant (scipy returns NaN in
    that case; normalized here rather than propagated to callers).
    """
    pairs = [
        (float(s), float(r))
        # strict=True: a length mismatch between scores and forward returns
        # is a caller bug (misaligned panel), not something to silently truncate.
        for s, r in zip(scores, forward_returns, strict=True)
        if s is not None and r is not None and not (_isnan(s) or _isnan(r))
    ]
    n = len(pairs)
    if n < 3:
        return {"ic": 0.0, "p_value": 1.0, "n": n, "method": method}

    x = [p[0] for p in pairs]
    y = [p[1] for p in pairs]

    corr_fn = pearsonr if method == "pearson" else spearmanr
    ic, p_value = corr_fn(x, y)
    ic = float(ic) if not math.isnan(ic) else 0.0
    p_value = float(p_value) if not math.isnan(p_value) else 1.0

    return {"ic": round(ic, 4), "p_value": round(p_value, 4), "n": n, "method": method}


def compute_cross_sectional_ic(
    panel: pd.DataFrame,
    score_col: str,
    forward_return_col: str,
    date_col: str = "date",
    method: str = "spearman",
) -> dict:
    """
    Per-date cross-sectional IC, then averaged across dates — the standard way
    to measure a ranking signal, and the honest counterpart to the pooled
    compute_information_coefficient above.

    Why this is the better number for a cross-sectional strategy: pooling every
    ticker-day into one correlation lets a few strong market-wide days dominate,
    and badly violates independence. Ranking within each date and averaging the
    per-date correlations asks the question the strategy actually acts on — "on
    a given day, does this score rank names correctly against each other?" — and
    the resulting series of per-date ICs is far closer to independent, so the
    t-statistic on its mean is meaningful.

    Returns {"mean_ic", "std_ic", "t_stat", "p_value", "n_dates", "ic_series"}.
    The Information Ratio of the signal is mean_ic / std_ic.
    """
    corr_fn = pearsonr if method == "pearson" else spearmanr
    per_date: list[float] = []
    dates: list = []

    for date, group in panel.groupby(date_col):
        sub = group[[score_col, forward_return_col]].dropna()
        if len(sub) < 3:
            continue
        if sub[score_col].nunique() < 2 or sub[forward_return_col].nunique() < 2:
            continue
        ic, _ = corr_fn(sub[score_col].to_numpy(), sub[forward_return_col].to_numpy())
        if not math.isnan(ic):
            per_date.append(float(ic))
            dates.append(date)

    n_dates = len(per_date)
    if n_dates < 3:
        return {
            "mean_ic": 0.0, "std_ic": 0.0, "t_stat": 0.0,
            "p_value": 1.0, "n_dates": n_dates,
            "ic_series": pd.Series(dtype=float),
        }

    arr = np.array(per_date, dtype=float)
    mean_ic = float(arr.mean())
    std_ic = float(arr.std(ddof=1))
    t_stat = mean_ic / (std_ic / math.sqrt(n_dates)) if std_ic > 0 else 0.0
    # Two-sided p-value from the normal approximation; n_dates is typically
    # in the hundreds for a monthly-or-finer panel, where t and z agree closely.
    p_value = float(2.0 * (1.0 - norm.cdf(abs(t_stat)))) if std_ic > 0 else 1.0

    return {
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_value, 4),
        "n_dates": n_dates,
        "ic_series": pd.Series(per_date, index=dates, name="ic"),
    }


def bootstrap_ic_ci(
    scores: Sequence[float],
    forward_returns: Sequence[float],
    method: str = "spearman",
    n_bootstrap: int = 10000,
    ci: float = 0.95,
    seed: int | None = 42,
) -> dict:
    """
    Bootstrap confidence interval on compute_information_coefficient's point
    estimate — a second, independent check on whether an IC is real.

    Resamples (score, return) PAIRS with replacement, not each series
    independently, preserving whatever real pairing structure exists.

    seed defaults to a fixed value so repeated calls on the same data give the
    same answer: this feeds go/no-go decisions, and a verdict that flips between
    runs from resampling noise would undermine the gate itself.

    Returns {"ic_mean", "ci_lower", "ci_upper", "n"}, all 0.0 when fewer than
    3 valid pairs exist.
    """
    pairs = [
        (float(s), float(r))
        # strict=True: a length mismatch between scores and forward returns
        # is a caller bug (misaligned panel), not something to silently truncate.
        for s, r in zip(scores, forward_returns, strict=True)
        if s is not None and r is not None and not (_isnan(s) or _isnan(r))
    ]
    n = len(pairs)
    if n < 3:
        return {"ic_mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n": n}

    x = np.array([p[0] for p in pairs], dtype=float)
    y = np.array([p[1] for p in pairs], dtype=float)
    corr_fn = pearsonr if method == "pearson" else spearmanr

    rng = np.random.default_rng(seed)
    boot_ics = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        ic_val, _ = corr_fn(x[idx], y[idx])
        boot_ics[i] = ic_val if not math.isnan(ic_val) else 0.0

    point_ic, _ = corr_fn(x, y)
    point_ic = float(point_ic) if not math.isnan(point_ic) else 0.0

    alpha = (1.0 - ci) / 2.0
    return {
        "ic_mean": round(point_ic, 4),
        "ci_lower": round(float(np.percentile(boot_ics, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(boot_ics, (1.0 - alpha) * 100)), 4),
        "n": n,
    }


def benjamini_hochberg_correction(p_values: list[float], fdr: float = 0.05) -> list[bool]:
    """
    Benjamini-Hochberg false-discovery-rate correction — flags which of a batch
    of p-values remain significant after accounting for having run that many
    tests at once.

    Chosen over Bonferroni as less conservative and the standard choice for an
    exploratory multi-test scan: Bonferroni controls the family-wise error rate
    (near-zero tolerance for any false positive in the batch); BH controls the
    expected false-discovery rate among what is flagged, which is the right bar
    for "is this worth investigating further" rather than "is this proven."

    Returns booleans in the same order/length as p_values.
    """
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(range(n), key=lambda i: p_values[i])
    significant = [False] * n
    # Largest k such that the k-th smallest p-value <= (k/n) * fdr — the
    # standard BH step-up procedure. Everything at or below that rank is flagged.
    largest_k = 0
    for rank, idx in enumerate(indexed, start=1):
        if p_values[idx] <= (rank / n) * fdr:
            largest_k = rank
    for rank, idx in enumerate(indexed, start=1):
        if rank <= largest_k:
            significant[idx] = True
    return significant


def bootstrap_mean_ci(
    values: Sequence[float],
    n_bootstrap: int = 10000,
    ci: float = 0.95,
    seed: int | None = 42,
) -> dict:
    """
    Bootstrap confidence interval on a mean — per-period return, per-trade
    R-multiple, whatever the caller is averaging.

    This answers "how confident can we be the true mean is above zero", which a
    bare point estimate cannot: a flat average says nothing about sample-size
    uncertainty, and can look decisive while resting on almost no data. V2's
    entire go-live history is the cautionary case.

    Fixed default seed, for the same determinism reason as bootstrap_ic_ci.

    Returns {"mean", "ci_lower", "ci_upper", "n"}, all 0.0 when values is empty.
    """
    if len(values) == 0:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n": 0}

    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n": 0}

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=arr.size, replace=True)
        boot_means[i] = sample.mean()

    alpha = (1.0 - ci) / 2.0
    return {
        "mean": float(arr.mean()),
        "ci_lower": float(np.percentile(boot_means, alpha * 100)),
        "ci_upper": float(np.percentile(boot_means, (1.0 - alpha) * 100)),
        "n": int(arr.size),
    }


# --------------------------------------------------------------------------
# Risk and return
# --------------------------------------------------------------------------

def compute_cagr(equity_curve: pd.Series, periods_per_year: float = 252) -> float:
    """
    Compound annual growth rate implied by an equity curve. `periods_per_year`
    must match what one step of the curve represents — 252 for daily, 12 for
    monthly. Returns a fraction (0.11 for 11%/yr).
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0
    start = float(equity_curve.iloc[0])
    end = float(equity_curve.iloc[-1])
    if start <= 0 or end <= 0:
        return 0.0
    years = (len(equity_curve) - 1) / periods_per_year
    if years <= 0:
        return 0.0
    return float((end / start) ** (1.0 / years) - 1.0)


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Peak-to-trough drawdown. Returns a positive fraction (0.15 for 15%).
    """
    if equity_curve.empty:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(abs(drawdown.min()))


def compute_max_drawdown_duration(equity_curve: pd.Series) -> int:
    """
    Longest stretch, in equity-curve steps, from a peak until a new high is
    made. max_drawdown alone doesn't say how long capital sat underwater — a
    portfolio flat for 8 months at "only 12%" down is a materially different
    experience to hold than one that recovers in 3 weeks, and the two are
    indistinguishable from depth alone.
    """
    if equity_curve.empty:
        return 0
    rolling_max = equity_curve.cummax()
    underwater = equity_curve < rolling_max
    max_duration = 0
    current_duration = 0
    for is_underwater in underwater:
        if is_underwater:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0
    return max_duration


def compute_ulcer_index(equity_curve: pd.Series) -> float:
    """
    Ulcer Index (Martin, 1987) — root-mean-square percentage drawdown across
    the whole curve, not just its worst point. Combines depth and duration into
    one number. Returns a percentage (8.2, not 0.082).
    """
    if equity_curve.empty:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdown_pct = (equity_curve - rolling_max) / rolling_max * 100
    return float((drawdown_pct.pow(2).mean()) ** 0.5)


def compute_sharpe(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: float = 252) -> float:
    """
    Annualized Sharpe ratio.

    `periods_per_year` must match what one step in `returns` represents: 252 for
    a daily series, 12 for monthly. Getting this wrong is not a rounding error —
    V2 reported a Sharpe of 9.10 for weeks because a trade-indexed curve was
    annualized as if each trade were a trading day.
    """
    if returns.empty or returns.std() == 0:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = returns - period_rf
    return float((excess.mean() / returns.std()) * math.sqrt(periods_per_year))


def compute_sortino(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: float = 252) -> float:
    """
    Annualized Sortino ratio — Sharpe's downside-only counterpart, penalizing
    only returns below the risk-free rate. Same periods_per_year caveat as
    compute_sharpe.
    """
    if returns.empty:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = returns - period_rf
    downside = excess[excess < 0]
    if len(downside) < 2:
        return 0.0
    downside_std = downside.std()
    if downside_std == 0 or math.isnan(downside_std):
        return 0.0
    return float((excess.mean() / downside_std) * math.sqrt(periods_per_year))


def compute_deflated_sharpe_ratio(
    sharpe_ratios: list[float],
    selected_sharpe: float,
    n_observations: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> dict:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014). Answers: given that
    `selected_sharpe` was picked as the best of `len(sharpe_ratios)` trials, how
    much of it is genuine edge versus what selection alone would produce?

    Report this whenever a parameter sweep preceded the headline number — which
    in practice means almost always.

    sharpe_ratios: per-trial Sharpe from every trial in the sweep, used to
      estimate the sampling variance of the Sharpe estimator. A wide spread
      across similar configs means more of any single Sharpe is noise.
    selected_sharpe: the Sharpe being reported (usually the max, but passed
      explicitly since selection may use another criterion).
    n_observations: number of return observations behind the selected Sharpe.
    skew / kurtosis: of the selected trial's return series. Defaults are a
      normal distribution's own moments, making the correction
      conservative-normal rather than silently wrong.

    Returns expected_max_sharpe_under_null, deflated_sharpe, psr, n_trials,
    n_observations. Act on `psr`: below ~0.95, the winning configuration's edge
    over chance is not convincing.
    """
    n_trials = len(sharpe_ratios)
    if n_trials == 0 or n_observations < 2:
        return {
            "expected_max_sharpe_under_null": 0.0,
            "deflated_sharpe": 0.0,
            "psr": 0.0,
            "n_trials": n_trials,
            "n_observations": n_observations,
        }

    # Sampling variance of the Sharpe estimator across trials. With one trial
    # there is no spread to estimate from, so fall back to the analytic
    # asymptotic variance of a single Sharpe estimate (B&LdP eq. 5) rather than
    # a degenerate zero-variance case.
    if n_trials > 1:
        var_sr = float(np.var(sharpe_ratios, ddof=1))
    else:
        var_sr = (1.0 + 0.5 * selected_sharpe ** 2) / max(n_observations - 1, 1)

    if var_sr <= 0 or n_trials <= 1:
        expected_max_sr = 0.0
    else:
        # Expected maximum of n_trials iid standard normal draws (B&LdP eq. 8),
        # scaled by the estimated Sharpe std dev — "how good would the best of
        # N noisy, edge-free trials look purely by luck."
        euler_mascheroni = 0.5772156649
        expected_max_sr = math.sqrt(var_sr) * (
            (1 - euler_mascheroni) * norm.ppf(1.0 - 1.0 / n_trials)
            + euler_mascheroni * norm.ppf(1.0 - 1.0 / (n_trials * math.e))
        )

    # Probabilistic Sharpe Ratio (B&LdP eq. 1) benchmarked against
    # expected_max_sr instead of 0; higher-moment terms correct for the selected
    # trial's return distribution not being normal.
    denom = math.sqrt(max(
        1e-12,
        1 - skew * selected_sharpe + ((kurtosis - 1) / 4.0) * selected_sharpe ** 2,
    ))
    psr = float(norm.cdf(
        (selected_sharpe - expected_max_sr) * math.sqrt(max(n_observations - 1, 1)) / denom
    ))

    return {
        "expected_max_sharpe_under_null": round(expected_max_sr, 4),
        "deflated_sharpe": round(selected_sharpe - expected_max_sr, 4),
        "psr": round(psr, 4),
        "n_trials": n_trials,
        "n_observations": n_observations,
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def summarize_returns(
    returns: pd.Series,
    periods_per_year: float = 252,
    risk_free_rate: float = 0.04,
) -> dict:
    """
    The standard bundle for any V3 strategy variant, computed from a periodic
    returns series. Every research script reports this, so variants are always
    compared on the same terms.
    """
    if returns.empty:
        return {
            "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0,
            "max_drawdown_duration": 0, "ulcer_index": 0.0,
            "volatility": 0.0, "n_periods": 0,
        }
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return {
        "cagr": round(compute_cagr(equity, periods_per_year), 4),
        "sharpe": round(compute_sharpe(returns, risk_free_rate, periods_per_year), 3),
        "sortino": round(compute_sortino(returns, risk_free_rate, periods_per_year), 3),
        "max_drawdown": round(compute_max_drawdown(equity), 4),
        "max_drawdown_duration": compute_max_drawdown_duration(equity),
        "ulcer_index": round(compute_ulcer_index(equity), 3),
        "volatility": round(float(returns.std() * math.sqrt(periods_per_year)), 4),
        "n_periods": int(len(returns)),
    }


def _isnan(value) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False
