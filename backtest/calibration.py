"""Calibration + maker/taker profitability check on pulled BTC-updown-5m trade history.

Methodology mirrors Jon-Becker/prediction-market-analysis's polymarket_win_rate_by_price.py
(Brier score / ECE / log loss by price) and maker_vs_taker_returns.py (excess return by
price for the taker vs the passive counterparty), computed directly on our own pulled
sample since that repo's packaged dataset doesn't cover this market (see design doc).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"


def load() -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / "trades.parquet")
    df["won"] = (df["outcome"] == df["winner"]).astype(int)
    df["price_bucket"] = (df["price"] * 100).round().clip(1, 99).astype(int)
    return df


def calibration_by_price(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("price_bucket").agg(
        n_trades=("won", "size"),
        wins=("won", "sum"),
        volume_usd=("size", lambda s: float((s * df.loc[s.index, "price"]).sum())),
    )
    g["win_rate"] = g["wins"] / g["n_trades"]
    g["implied_prob"] = g.index / 100.0
    g["edge_pp"] = (g["win_rate"] - g["implied_prob"]) * 100
    return g.reset_index()


def calibration_metrics(df: pd.DataFrame) -> dict:
    p = df["price"].clip(1e-6, 1 - 1e-6)
    y = df["won"]
    brier = float(((p - y) ** 2).mean())
    log_loss = float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())

    bucketed = calibration_by_price(df)
    total = bucketed["n_trades"].sum()
    ece = float((bucketed["n_trades"] * (bucketed["win_rate"] - bucketed["implied_prob"]).abs()).sum() / total)

    return {
        "n_trades": int(len(df)),
        "n_windows": int(df["slug"].nunique()),
        "brier_score": round(brier, 4),
        "log_loss": round(log_loss, 4),
        "ece": round(ece, 4),
        "overall_win_rate_up": round(float(df.loc[df["outcome"] == "Up", "won"].mean()), 4),
    }


def maker_taker_excess_by_price(df: pd.DataFrame) -> pd.DataFrame:
    """Taker excess return by price, and the passive counterparty's implied excess.

    'side' is the taker's side on that fill. A BUY at price p means the taker paid p for
    a share of `outcome`; a SELL at price p means the taker received p for a share of
    `outcome` (closing/opening the opposite exposure). We treat every row as a taker
    position at (price, outcome, won) and compute excess = win_rate - price for BUY rows;
    for SELL rows the taker's economic position is short that outcome, so we flip it:
    excess = (1 - win_rate) - (1 - price) = price - win_rate.
    """
    buys = df[df["side"] == "BUY"].copy()
    sells = df[df["side"] == "SELL"].copy()

    buy_stats = buys.groupby("price_bucket").agg(n=("won", "size"), win_rate=("won", "mean"))
    buy_stats["taker_excess_pp"] = (buy_stats["win_rate"] - buy_stats.index / 100.0) * 100

    sell_stats = sells.groupby("price_bucket").agg(n=("won", "size"), win_rate=("won", "mean"))
    sell_stats["taker_excess_pp"] = (sell_stats.index / 100.0 - sell_stats["win_rate"]) * 100

    out = pd.concat(
        [buy_stats.add_prefix("buy_"), sell_stats.add_prefix("sell_")], axis=1
    ).reset_index().rename(columns={"index": "price_bucket"})
    return out


def main() -> None:
    df = load()
    metrics = calibration_metrics(df)
    print("=== Calibration metrics ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    cal = calibration_by_price(df)
    print("\n=== Win rate vs implied price (5c buckets) ===")
    cal["bucket5"] = (cal["price_bucket"] // 5) * 5
    summary = cal.groupby("bucket5").apply(
        lambda g: pd.Series(
            {
                "n_trades": g["n_trades"].sum(),
                "volume_usd": g["volume_usd"].sum(),
                "avg_win_rate": np.average(g["win_rate"], weights=g["n_trades"]),
                "avg_implied": np.average(g["implied_prob"], weights=g["n_trades"]),
            }
        ),
        include_groups=False,
    )
    summary["edge_pp"] = (summary["avg_win_rate"] - summary["avg_implied"]) * 100
    print(summary.round(4).to_string())

    print("\n=== Volume concentration by price band ===")
    total_vol = cal["volume_usd"].sum()
    for lo, hi, label in [
        (40, 60, "40-60c (mid, reward-curve peak)"),
        (20, 40, "20-40c"),
        (60, 80, "60-80c"),
        (5, 20, "5-20c"),
        (80, 95, "80-95c"),
        (0, 5, "0-5c + 95-100c (extremes)"),
    ]:
        if lo == 0:
            band = cal[((cal["price_bucket"] >= 0) & (cal["price_bucket"] < 5)) | (cal["price_bucket"] >= 95)]
        else:
            band = cal[(cal["price_bucket"] >= lo) & (cal["price_bucket"] < hi)]
        pct = 100 * band["volume_usd"].sum() / total_vol
        print(f"  {label}: {pct:.1f}% of volume")

    print("\n=== Window-level calibration (one obs per window x outcome x 5c bucket, avoids trade-count clustering) ===")
    per_window_bucket = (
        df.groupby(["slug", "outcome", "price_bucket"])
        .agg(won=("won", "first"), n_trades=("won", "size"))
        .reset_index()
    )
    assert (
        df.groupby(["slug", "outcome", "price_bucket"])["won"].nunique().max() == 1
    ), "won should be constant within (slug, outcome, price_bucket)"
    per_window_bucket["bucket5"] = (per_window_bucket["price_bucket"] // 5) * 5
    wb = per_window_bucket.groupby("bucket5").agg(
        n_window_obs=("won", "size"),
        n_distinct_windows=("slug", "nunique"),
        win_rate=("won", "mean"),
    )
    wb["implied"] = wb.index / 100.0
    wb["edge_pp"] = (wb["win_rate"] - wb["implied"]) * 100
    print(wb.round(4).to_string())
    print(
        f"\n  (total distinct windows in sample: {df['slug'].nunique()} -- "
        "treat any single bucket's edge_pp as noisy until n_distinct_windows is large)"
    )

    mt = maker_taker_excess_by_price(df)
    print("\n=== Taker excess return by price (10c buckets, BUY side) ===")
    mt["bucket10"] = (mt["price_bucket"] // 10) * 10
    buy_summary = mt.dropna(subset=["buy_n"]).groupby("bucket10").apply(
        lambda g: pd.Series(
            {
                "n": g["buy_n"].sum(),
                "taker_excess_pp": np.average(g["buy_taker_excess_pp"], weights=g["buy_n"]),
            }
        ),
        include_groups=False,
    )
    print(buy_summary.round(3).to_string())

    cal.to_csv(DATA_DIR / "calibration_by_price.csv", index=False)
    mt.to_csv(DATA_DIR / "maker_taker_by_price.csv", index=False)
    print(f"\nWrote {DATA_DIR / 'calibration_by_price.csv'} and maker_taker_by_price.csv")


if __name__ == "__main__":
    main()
