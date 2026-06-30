"""
SHARED: Computes high/low volume nodes at price levels for target + stop placement.
Price tends to move quickly through low-volume areas and stall at high-volume nodes.
Used by risk_reward.py for defensible stop/target placement and by scoring.py
for the volume_profile technical sub-signal (0-12 points).
"""

from typing import Optional

import numpy as np
import pandas as pd


def compute_volume_profile(
    ohlcv: pd.DataFrame,
    lookback_days: int = 60,
    price_bucket_pct: float = 0.005,
) -> pd.DataFrame:
    """
    Build volume profile: distribute each day's volume across price buckets.

    Each day's volume is split evenly across the OHLC price range for that bar.
    Bucket width = price_bucket_pct × close price (proportional buckets).

    Returns DataFrame indexed by price_level (midpoint of each bucket):
    [volume_at_level, volume_pct, is_high_volume_node, is_low_volume_node]

    High-volume node: volume_at_level > 1.5× median bucket volume
    Low-volume node:  volume_at_level < 0.5× median bucket volume
    """
    df = ohlcv.tail(lookback_days).copy()
    if df.empty:
        return pd.DataFrame(columns=["volume_at_level", "volume_pct",
                                     "is_high_volume_node", "is_low_volume_node"])

    price_min = float(df["Low"].min())
    price_max = float(df["High"].max())
    if price_min <= 0 or price_max <= price_min:
        return pd.DataFrame(columns=["volume_at_level", "volume_pct",
                                     "is_high_volume_node", "is_low_volume_node"])

    # Build fixed-width buckets across the price range
    bucket_width = (price_min + price_max) / 2 * price_bucket_pct
    if bucket_width <= 0:
        bucket_width = 0.01

    num_buckets = max(1, int((price_max - price_min) / bucket_width) + 1)
    bucket_edges = [price_min + i * bucket_width for i in range(num_buckets + 1)]
    bucket_midpoints = [(bucket_edges[i] + bucket_edges[i + 1]) / 2 for i in range(num_buckets)]
    volume_buckets = [0.0] * num_buckets

    for _, row in df.iterrows():
        lo = float(row["Low"])
        hi = float(row["High"])
        vol = float(row["Volume"])
        if hi <= lo or vol == 0:
            continue
        # Count how many buckets this bar's range touches
        first_bucket = max(0, int((lo - price_min) / bucket_width))
        last_bucket = min(num_buckets - 1, int((hi - price_min) / bucket_width))
        n_touched = last_bucket - first_bucket + 1
        vol_per_bucket = vol / n_touched
        for b in range(first_bucket, last_bucket + 1):
            volume_buckets[b] += vol_per_bucket

    total_vol = sum(volume_buckets) or 1.0
    median_vol = float(np.median([v for v in volume_buckets if v > 0])) if any(
        v > 0 for v in volume_buckets) else 1.0

    records = []
    for i, mid in enumerate(bucket_midpoints):
        v = volume_buckets[i]
        records.append({
            "price_level": round(mid, 4),
            "volume_at_level": v,
            "volume_pct": v / total_vol,
            "is_high_volume_node": v > 1.5 * median_vol,
            "is_low_volume_node": v < 0.5 * median_vol,
        })

    result = pd.DataFrame(records).set_index("price_level")
    return result


def find_nearest_support_node(
    price: float,
    volume_profile: pd.DataFrame,
    direction: str = "below",
) -> Optional[float]:
    """
    Find nearest high-volume node below (direction='below') or above (direction='above') price.
    Used for ATR stop placement — stops anchored at high-volume nodes are more defensible.
    Returns the price level or None if no high-volume node found.
    """
    if volume_profile.empty:
        return None

    hvn = volume_profile[volume_profile["is_high_volume_node"]]
    if hvn.empty:
        return None

    levels = hvn.index.tolist()

    if direction == "below":
        below = [lv for lv in levels if lv < price]
        return max(below) if below else None
    else:
        above = [lv for lv in levels if lv > price]
        return min(above) if above else None


def find_nearest_low_volume_area(
    price: float,
    volume_profile: pd.DataFrame,
    direction: str = "above",
) -> Optional[float]:
    """
    Find next low-volume price area above (bullish target) or below (bearish target).
    Price travels quickly through low-volume areas → used as initial price targets.
    Returns the price level or None if no low-volume node found.
    """
    if volume_profile.empty:
        return None

    lvn = volume_profile[volume_profile["is_low_volume_node"]]
    if lvn.empty:
        return None

    levels = lvn.index.tolist()

    if direction == "above":
        above = [lv for lv in levels if lv > price]
        return min(above) if above else None
    else:
        below = [lv for lv in levels if lv < price]
        return max(below) if below else None


def score_volume_profile_position(
    current_price: float,
    volume_profile: pd.DataFrame,
) -> float:
    """
    Score 0-12: how well the current price is positioned relative to volume nodes.

    Scoring logic:
    - Price just above a high-volume node (≤2% above) → strong support → 10-12
    - Price well above a high-volume node (2-8% above) → moderate support → 6-10
    - Price within a high-volume node → resistance zone → 3-6
    - Price in a low-volume area → momentum possible but no support → 4-8
    - Price below all HVNs → no support → 0-3
    """
    if volume_profile.empty:
        return 6.0  # neutral when no profile available

    support = find_nearest_support_node(current_price, volume_profile, direction="below")

    if support is None:
        return 2.0  # No support found → bearish position

    pct_above = (current_price - support) / support
    if pct_above <= 0.02:
        return 12.0  # Price sitting just above a major support node
    if pct_above <= 0.05:
        return 9.0
    if pct_above <= 0.10:
        return 7.0
    if pct_above <= 0.20:
        return 5.0
    return 3.0  # Far above support — extended, risk of pullback
