from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

WINDOW_SECONDS = 300


@dataclass(frozen=True)
class WindowInfo:
    slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    start_ts: int
    end_ts: int
    max_spread_cents: float
    min_reward_size: float
    tick_size: float


def parse_window_event(event: dict, start_ts: int) -> WindowInfo | None:
    if not event or not event.get("markets"):
        return None
    market = event["markets"][0]
    try:
        outcomes = json.loads(market["outcomes"])
        token_ids = json.loads(market["clobTokenIds"])
    except (KeyError, json.JSONDecodeError, TypeError):
        return None
    if outcomes != ["Up", "Down"] or len(token_ids) != 2:
        return None
    return WindowInfo(
        slug=event["slug"],
        condition_id=market["conditionId"],
        up_token_id=token_ids[0],
        down_token_id=token_ids[1],
        start_ts=start_ts,
        end_ts=start_ts + WINDOW_SECONDS,
        max_spread_cents=float(market["rewardsMaxSpread"]),
        min_reward_size=float(market["rewardsMinSize"]),
        tick_size=float(market["orderPriceMinTickSize"]),
    )


class MarketTracker:
    def __init__(self, gamma_host: str = "https://gamma-api.polymarket.com", _session: Any = None) -> None:
        self._gamma_host = gamma_host
        self._session = _session if _session is not None else requests.Session()

    def fetch_window(self, start_ts: int) -> WindowInfo | None:
        slug = f"btc-updown-5m-{start_ts}"
        response = self._session.get(f"{self._gamma_host}/events", params={"slug": slug}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        return parse_window_event(data[0], start_ts)

    def current_window_start(self, now_ts: float | None = None) -> int:
        now_ts = now_ts if now_ts is not None else time.time()
        return int(now_ts // WINDOW_SECONDS) * WINDOW_SECONDS
