from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections import deque
from pathlib import Path

from polymarket_mm_bot.clob_client import DryRunClobClient, LiveClobClient
from polymarket_mm_bot.config import Config
from polymarket_mm_bot.dashboard_state import build_state_snapshot, write_state_snapshot
from polymarket_mm_bot.inventory import InventoryTracker
from polymarket_mm_bot.kill_switch import KillSwitch
from polymarket_mm_bot.market_data import MarketDataClient
from polymarket_mm_bot.market_tracker import MarketTracker
from polymarket_mm_bot.order_manager import OrderManager
from polymarket_mm_bot.quote_engine import compute_ladder
from polymarket_mm_bot.redemption import (
    DryRunRedeemer,
    RedemptionClient,
    RedemptionRetryQueue,
    RedeemerProtocol,
    should_attempt_redemption,
)
from polymarket_mm_bot.window_closer import WindowCloser, should_pull_quotes

logger = logging.getLogger("polymarket_mm_bot")
POLL_SECONDS = 2.0

# Polygon mainnet addresses for Polymarket's ConditionalTokens (CTF) and
# USDC.e collateral - fixed platform constants, not per-user config. Verified
# live against py-clob-client's own contract config while building the
# redemption module.
POLYGON_CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
POLYGON_COLLATERAL_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


def _attempt_redemption(
    redeemer: RedeemerProtocol,
    retry_queue: RedemptionRetryQueue,
    condition_id: str,
    label: str,
) -> str | None:
    """Tries to redeem one condition_id; on failure, records it in the retry
    queue instead of just logging and forgetting. Shared by the
    just-closed-window redemption and the pending-retry sweep below. Returns
    the tx hash on success, None on failure (used to drive dashboard events)."""
    try:
        tx_hash = redeemer.redeem(condition_id)
        logger.info("redeemed %s -> %s", label, tx_hash)
        retry_queue.record_success(condition_id)
        return tx_hash
    except Exception:
        just_exhausted = retry_queue.record_failure(condition_id)
        attempts = retry_queue.attempt_count(condition_id)
        if just_exhausted:
            logger.error(
                "redemption for %s failed %d times, giving up automatic retries - redeem manually",
                label, attempts,
            )
        else:
            logger.exception(
                "redemption failed for %s (attempt %d), will retry next rollover", label, attempts
            )
        return None


async def run(
    config: Config,
    flag_path: Path,
    redemption_state_path: Path,
    dashboard_state_path: Path | None = None,
) -> None:
    order_client = (
        DryRunClobClient()
        if config.dry_run
        else LiveClobClient(
            host=config.clob_host,
            private_key=config.private_key,
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.api_passphrase,
            funder=config.funder_address,
        )
    )
    redeemer = (
        DryRunRedeemer()
        if config.dry_run
        else RedemptionClient(
            rpc_url=config.polygon_rpc_url,
            private_key=config.private_key,
            conditional_tokens_address=POLYGON_CONDITIONAL_TOKENS_ADDRESS,
            collateral_address=POLYGON_COLLATERAL_ADDRESS,
        )
    )
    market_data = MarketDataClient(host=config.clob_host)
    tracker = MarketTracker(gamma_host=config.gamma_host)
    order_manager = OrderManager(order_client)
    window_closer = WindowCloser(order_client, config.pull_quote_seconds_before_close)
    inventory = InventoryTracker()
    kill_switch = KillSwitch(flag_path)
    retry_queue = RedemptionRetryQueue(
        max_attempts=config.redemption_max_attempts, state_path=redemption_state_path
    )
    recent_events: deque[dict] = deque(maxlen=20)
    last_redemption: dict | None = None

    def _record_event(now: float, message: str) -> None:
        recent_events.append({"at": now, "message": message})

    def _write_snapshot(now: float, window_, midpoint_up_, skew_, plan_) -> None:
        if dashboard_state_path is None:
            return
        snapshot = build_state_snapshot(
            now=now,
            dry_run=config.dry_run,
            window=window_,
            midpoint_up=midpoint_up_,
            skew=skew_,
            inventory=inventory,
            plan=plan_,
            last_redemption=last_redemption,
            retry_queue=retry_queue,
            recent_events=list(recent_events),
        )
        write_state_snapshot(dashboard_state_path, snapshot)

    window = tracker.fetch_window(tracker.current_window_start())

    while True:
        if kill_switch.is_triggered():
            logger.warning("kill switch triggered: cancelling all orders and stopping")
            order_client.cancel_all()
            _record_event(time.time(), "kill switch triggered, stopped")
            _write_snapshot(time.time(), window, None, 0.0, None)
            return

        now = time.time()
        new_start = tracker.current_window_start(now)
        if window is None or new_start != window.start_ts:
            previous_window = window
            if previous_window is not None and should_attempt_redemption(inventory.up_shares, inventory.down_shares):
                tx_hash = _attempt_redemption(redeemer, retry_queue, previous_window.condition_id, previous_window.slug)
                if tx_hash is not None:
                    last_redemption = {"slug": previous_window.slug, "tx_hash": tx_hash, "at": now}
                    _record_event(now, f"redeemed {previous_window.slug} -> {tx_hash}")

            # Sweep anything still owed from earlier failed attempts. Bounded
            # by retry_queue's max_attempts, so this can't grow unbounded work
            # per rollover - it only ever retries what's still pending.
            for condition_id in retry_queue.pending():
                tx_hash = _attempt_redemption(redeemer, retry_queue, condition_id, condition_id)
                if tx_hash is not None:
                    last_redemption = {"slug": condition_id, "tx_hash": tx_hash, "at": now}
                    _record_event(now, f"retried redemption succeeded -> {tx_hash}")

            window = tracker.fetch_window(new_start)
            inventory.reset()
            if window is not None:
                _record_event(now, f"window {window.slug} opened")
            if window is None:
                logger.warning("no window found for start_ts=%s, retrying next poll", new_start)
                _write_snapshot(now, None, None, 0.0, None)
                await asyncio.sleep(POLL_SECONDS)
                continue

        if should_pull_quotes(now, window.end_ts, config.pull_quote_seconds_before_close):
            if window_closer.maybe_pull_quotes(window, now):
                logger.info("pulled quotes for %s ahead of resolution", window.slug)
                _record_event(now, f"pulled quotes for {window.slug} ahead of resolution")
            _write_snapshot(now, window, None, 0.0, None)
            await asyncio.sleep(POLL_SECONDS)
            continue

        fills = order_client.get_fills(window.condition_id, window.start_ts)
        inventory.sync_from_fills(fills, window.up_token_id, window.down_token_id)

        midpoint_up = market_data.get_midpoint(window.up_token_id)
        skew = inventory.skew(config.imbalance_ceiling_shares)
        plan = compute_ladder(
            midpoint_up=midpoint_up,
            max_spread_cents=window.max_spread_cents,
            tick_size=window.tick_size,
            min_reward_size=window.min_reward_size,
            capital_usd=config.capital_per_window_usd,
            n_levels_per_side=config.n_ladder_levels,
            inventory_skew=skew,
        )
        logger.info(
            "window=%s midpoint_up=%.3f skew=%.2f levels=%d total_cost=$%.2f dry_run=%s",
            window.slug, midpoint_up, skew, len(plan.levels), plan.total_cost_usd, config.dry_run,
        )
        order_manager.reconcile(plan, window)
        _write_snapshot(now, window, midpoint_up, skew, plan)

        await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--flag-file", type=Path, default=Path(".stop"))
    parser.add_argument("--redemption-state-file", type=Path, default=Path(".redemption_queue.json"))
    parser.add_argument("--dashboard-state-file", type=Path, default=Path("dashboard/state.json"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env(env_path=args.env_file)
    asyncio.run(run(config, args.flag_file, args.redemption_state_file, args.dashboard_state_file))


if __name__ == "__main__":
    main()
