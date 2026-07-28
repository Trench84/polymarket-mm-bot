from __future__ import annotations

import json
from pathlib import Path

from polymarket_mm_bot.inventory import InventoryTracker
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.quote_engine import LadderPlan
from polymarket_mm_bot.redemption import RedemptionRetryQueue


def build_state_snapshot(
    now: float,
    dry_run: bool,
    window: WindowInfo | None,
    midpoint_up: float | None,
    skew: float,
    inventory: InventoryTracker,
    plan: LadderPlan | None,
    last_redemption: dict | None,
    retry_queue: RedemptionRetryQueue,
    recent_events: list[dict],
) -> dict:
    """Pure snapshot of everything the dashboard needs to render, taken
    directly from the bot's live in-memory state each loop iteration. No I/O -
    see write_state_snapshot() for the (equally simple) disk-write side."""
    window_dict = None
    if window is not None:
        window_dict = {
            "slug": window.slug,
            "start_ts": window.start_ts,
            "end_ts": window.end_ts,
            "seconds_remaining": max(0.0, window.end_ts - now),
        }

    levels: list[dict] = []
    total_cost_usd = 0.0
    if plan is not None:
        levels = [{"token": level.token, "price": level.price, "size": level.size} for level in plan.levels]
        total_cost_usd = plan.total_cost_usd

    return {
        "generated_at": now,
        "dry_run": dry_run,
        "window": window_dict,
        "midpoint_up": midpoint_up,
        "skew": skew,
        "inventory": {
            "up_shares": inventory.up_shares,
            "down_shares": inventory.down_shares,
            "net_shares": inventory.net_shares,
        },
        "ladder": {"levels": levels, "total_cost_usd": total_cost_usd},
        "redemption": {
            "last": last_redemption,
            "pending_count": len(retry_queue.pending()),
            "exhausted": retry_queue.exhausted(),
        },
        "recent_events": recent_events,
    }


def write_state_snapshot(path: Path, snapshot: dict) -> None:
    """Atomic write (temp file + rename) so a browser polling this file every
    second never reads a half-written, invalid-JSON snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(snapshot))
    tmp_path.replace(path)
