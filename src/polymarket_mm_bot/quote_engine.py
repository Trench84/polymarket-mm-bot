from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Token = Literal["UP", "DOWN"]


@dataclass(frozen=True)
class LadderLevel:
    token: Token
    price: float
    size: float


@dataclass(frozen=True)
class LadderPlan:
    levels: list[LadderLevel]

    @property
    def total_cost_usd(self) -> float:
        return sum(l.price * l.size for l in self.levels)


def floor_to_tick(price: float, tick: float) -> float:
    steps = int(price / tick + 1e-9)
    return round(steps * tick, 8)


def compute_ladder(
    midpoint_up: float,
    max_spread_cents: float,
    tick_size: float,
    min_reward_size: float,
    capital_usd: float,
    n_levels_per_side: int,
    inventory_skew: float,
) -> LadderPlan:
    """Build a two-sided BUY-only ladder centered on the live midpoint.

    Levels are placed at offsets from the midpoint (not an absolute price band) so
    they always stay within the market's own Liquidity Rewards max-spread cutoff.
    Sizing uses the same quadratic shape as Polymarket's own reward scoring
    function, so capital naturally concentrates where fills pay the most rebate.
    `inventory_skew` in [-1, 1] shifts capital between the UP/DOWN legs: positive
    means net long UP, so UP buys shrink and DOWN buys grow, pulling the position
    back toward flat.
    """
    midpoint_up = min(max(midpoint_up, 0.02), 0.98)
    max_spread = max_spread_cents / 100.0
    skew = min(max(inventory_skew, -1.0), 1.0)

    up_fraction = 0.5 - 0.5 * skew
    down_fraction = 0.5 + 0.5 * skew

    offsets = [max_spread * (i + 0.5) / n_levels_per_side for i in range(n_levels_per_side)]
    raw_weights = [((max_spread - o) / max_spread) ** 2 for o in offsets]
    weight_sum = sum(raw_weights)
    weights = [w / weight_sum for w in raw_weights]

    levels: list[LadderLevel] = []
    for token, fraction, mid in (
        ("UP", up_fraction, midpoint_up),
        ("DOWN", down_fraction, 1.0 - midpoint_up),
    ):
        side_capital = capital_usd * fraction
        for offset, weight in zip(offsets, weights):
            price = floor_to_tick(mid - offset, tick_size)
            price = min(max(price, tick_size), 1.0 - tick_size)
            level_capital = side_capital * weight
            size = level_capital / price
            if size < min_reward_size:
                continue
            levels.append(LadderLevel(token=token, price=price, size=round(size, 2)))

    return LadderPlan(levels=levels)
