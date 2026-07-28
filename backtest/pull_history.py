"""Pull recent BTC Up/Down 5-min window history + trades from Polymarket's public APIs.

Walks the fixed-cadence "btc-updown-5m-<unix_start_ts>" event slugs backwards in 300s
steps from a given anchor timestamp, fetching each window's resolution (Gamma events API)
and its trades (data-api). Writes two parquet files under backtest/data/.

This intentionally bypasses the on-chain indexer approach from the
Jon-Becker/prediction-market-analysis repo (see design doc) since it only needs one
market series and the CLOB-facing REST APIs already return clean, priced trade records.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import requests

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
DATA_API_TRADES_URL = "https://data-api.polymarket.com/trades"
WINDOW_SECONDS = 300
DATA_DIR = Path(__file__).parent / "data"

session = requests.Session()
session.headers.update({"User-Agent": "polymarket-mm-bot-backtest/0.1"})


def fetch_event(slug: str) -> dict | None:
    resp = session.get(GAMMA_EVENTS_URL, params={"slug": slug}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return None
    return data[0]


def fetch_trades(condition_id: str) -> list[dict]:
    trades: list[dict] = []
    offset = 0
    limit = 500
    while True:
        resp = session.get(
            DATA_API_TRADES_URL,
            params={"market": condition_id, "limit": limit, "offset": offset},
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        trades.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return trades


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=int, default=None, help="unix start ts of the most recent window to include")
    parser.add_argument("--windows", type=int, default=500, help="number of 5-min windows to walk back")
    parser.add_argument("--sleep", type=float, default=0.15, help="seconds to sleep between API calls")
    args = parser.parse_args()

    anchor = args.anchor or (int(time.time()) // WINDOW_SECONDS) * WINDOW_SECONDS

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    markets_rows = []
    trades_rows = []

    ts = anchor
    fetched = 0
    misses = 0
    for i in range(args.windows):
        slug = f"btc-updown-5m-{ts}"
        ts -= WINDOW_SECONDS
        try:
            event = fetch_event(slug)
        except requests.RequestException as e:
            print(f"[warn] {slug}: {e}")
            continue
        time.sleep(args.sleep)

        if not event or not event.get("markets"):
            misses += 1
            continue

        m = event["markets"][0]
        if not m.get("closed"):
            continue

        try:
            outcomes = json.loads(m["outcomes"])
            outcome_prices = json.loads(m["outcomePrices"])
        except (KeyError, json.JSONDecodeError, TypeError):
            continue

        # A resolved binary market has one outcome price ~1 and the other ~0
        prices = [float(p) for p in outcome_prices]
        if max(prices) < 0.99:
            continue  # not cleanly resolved yet, skip
        winner = outcomes[prices.index(max(prices))]

        condition_id = m["conditionId"]
        markets_rows.append(
            {
                "slug": slug,
                "condition_id": condition_id,
                "start_ts": ts + WINDOW_SECONDS,
                "winner": winner,
                "volume": float(m.get("volume") or 0),
            }
        )

        try:
            trades = fetch_trades(condition_id)
        except requests.RequestException as e:
            print(f"[warn] trades for {slug}: {e}")
            trades = []
        time.sleep(args.sleep)

        for t in trades:
            trades_rows.append(
                {
                    "slug": slug,
                    "condition_id": condition_id,
                    "price": float(t["price"]),
                    "size": float(t["size"]),
                    "side": t["side"],
                    "outcome": t["outcome"],
                    "timestamp": int(t["timestamp"]),
                    "proxy_wallet": t["proxyWallet"],
                    "tx_hash": t.get("transactionHash"),
                    "winner": winner,
                }
            )

        fetched += 1
        if fetched % 25 == 0:
            print(f"...{fetched} windows fetched, {len(trades_rows)} trades so far ({misses} misses)")

    markets_df = pd.DataFrame(markets_rows)
    trades_df = pd.DataFrame(trades_rows)
    if not trades_df.empty:
        before = len(trades_df)
        trades_df = trades_df.drop_duplicates()
        if len(trades_df) < before:
            print(f"Dropped {before - len(trades_df)} duplicate trade rows")

    markets_df.to_parquet(DATA_DIR / "windows.parquet", index=False)
    trades_df.to_parquet(DATA_DIR / "trades.parquet", index=False)

    print(
        f"Done. {len(markets_df)} resolved windows, {len(trades_df)} trades. "
        f"({misses} slug misses out of {args.windows} attempted)"
    )


if __name__ == "__main__":
    main()
