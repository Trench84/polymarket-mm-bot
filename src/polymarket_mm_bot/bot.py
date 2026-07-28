from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from polymarket_mm_bot.clob_client import DryRunClobClient, LiveClobClient
from polymarket_mm_bot.config import Config
from polymarket_mm_bot.inventory import InventoryTracker
from polymarket_mm_bot.kill_switch import KillSwitch
from polymarket_mm_bot.market_data import MarketDataClient
from polymarket_mm_bot.market_tracker import MarketTracker
from polymarket_mm_bot.order_manager import OrderManager
from polymarket_mm_bot.quote_engine import compute_ladder
from polymarket_mm_bot.window_closer import WindowCloser, should_pull_quotes

logger = logging.getLogger("polymarket_mm_bot")
POLL_SECONDS = 2.0


async def run(config: Config, flag_path: Path) -> None:
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
    market_data = MarketDataClient(host=config.clob_host)
    tracker = MarketTracker(gamma_host=config.gamma_host)
    order_manager = OrderManager(order_client)
    window_closer = WindowCloser(order_client, config.pull_quote_seconds_before_close)
    inventory = InventoryTracker()
    kill_switch = KillSwitch(flag_path)

    window = tracker.fetch_window(tracker.current_window_start())

    while True:
        if kill_switch.is_triggered():
            logger.warning("kill switch triggered: cancelling all orders and stopping")
            order_client.cancel_all()
            return

        now = time.time()
        new_start = tracker.current_window_start(now)
        if window is None or new_start != window.start_ts:
            window = tracker.fetch_window(new_start)
            inventory.reset()
            if window is None:
                logger.warning("no window found for start_ts=%s, retrying next poll", new_start)
                await asyncio.sleep(POLL_SECONDS)
                continue

        if should_pull_quotes(now, window.end_ts, config.pull_quote_seconds_before_close):
            if window_closer.maybe_pull_quotes(window, now):
                logger.info("pulled quotes for %s ahead of resolution", window.slug)
            await asyncio.sleep(POLL_SECONDS)
            continue

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

        await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--flag-file", type=Path, default=Path(".stop"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env(env_path=args.env_file)
    asyncio.run(run(config, args.flag_file))


if __name__ == "__main__":
    main()
