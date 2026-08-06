"""
Weighted isotonic regression via the Pool Adjacent Violators Algorithm (PAVA)
— used to smooth a noisy (confidence threshold -> historical win rate) curve
into a proper non-decreasing calibration mapping (see
swing_model/win_probability_calibration.py) without pulling in scikit-learn
as a new project dependency for one small, well-understood algorithm.
"""

from typing import Optional


def isotonic_regression(values: list[float], weights: Optional[list[float]] = None) -> list[float]:
    """
    Weighted PAVA: returns fitted values, same length and order as `values`,
    that are non-decreasing and minimize the weighted sum of squared
    deviations from the input — the standard isotonic regression solution.

    values/weights must already be ordered by whatever the real independent
    variable is (e.g. ascending confidence threshold) — this function only
    knows about position in the list, not any x-coordinate.

    weights: defaults to equal weight (1.0) per point. In the calibration use
    case, pass the number of qualifying trades backing each threshold's win
    rate — a win rate estimated from 300 trades should pull the fit harder
    than one estimated from 20.
    """
    n = len(values)
    if n == 0:
        return []
    if weights is None:
        weights = [1.0] * n

    # Stack of pooled blocks: parallel lists of (weighted mean, total weight,
    # start index). Each new point may merge backward into the block(s)
    # before it whenever it would otherwise violate monotonicity — merging
    # re-averages the *whole* accumulated block (via its running weight), not
    # just the two most recent raw points, so a block of 3+ points ends up
    # with the correct overall weighted mean.
    block_value: list[float] = []
    block_weight: list[float] = []
    block_start: list[int] = []

    for i in range(n):
        block_value.append(values[i])
        block_weight.append(weights[i])
        block_start.append(i)
        while len(block_value) >= 2 and block_value[-2] > block_value[-1]:
            w2, v2, _s2 = block_weight.pop(), block_value.pop(), block_start.pop()
            w1, v1, s1 = block_weight.pop(), block_value.pop(), block_start.pop()
            merged_w = w1 + w2
            merged_v = (v1 * w1 + v2 * w2) / merged_w if merged_w > 0 else v2
            block_value.append(merged_v)
            block_weight.append(merged_w)
            block_start.append(s1)

    result = [0.0] * n
    ends = block_start[1:] + [n]
    for value, start, end in zip(block_value, block_start, ends):
        for idx in range(start, end):
            result[idx] = value
    return result
