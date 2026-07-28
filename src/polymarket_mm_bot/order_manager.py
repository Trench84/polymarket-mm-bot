from __future__ import annotations

from dataclasses import dataclass

from polymarket_mm_bot.clob_client import ClobClientProtocol, OrderIntent, PlacedOrder
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.quote_engine import LadderPlan, floor_to_tick


@dataclass(frozen=True)
class ResolvedLevel:
    token_id: str
    price: float
    size: float


def resolve_ladder(plan: LadderPlan, window: WindowInfo) -> list[ResolvedLevel]:
    token_id_by_side = {"UP": window.up_token_id, "DOWN": window.down_token_id}
    return [
        ResolvedLevel(token_id=token_id_by_side[level.token], price=level.price, size=level.size)
        for level in plan.levels
    ]


def diff_orders(
    target: list[ResolvedLevel],
    resting: list[PlacedOrder],
    tick_size: float,
) -> tuple[list[ResolvedLevel], list[str]]:
    def order_key(price: float) -> float:
        return floor_to_tick(price, tick_size)

    target_keys = {(level.token_id, order_key(level.price)) for level in target}
    resting_by_key = {(order.token_id, order_key(order.price)): order for order in resting}

    to_place = [level for level in target if (level.token_id, order_key(level.price)) not in resting_by_key]
    to_cancel = [order.order_id for key, order in resting_by_key.items() if key not in target_keys]
    return to_place, to_cancel


class OrderManager:
    def __init__(self, client: ClobClientProtocol) -> None:
        self._client = client

    def reconcile(self, plan: LadderPlan, window: WindowInfo) -> None:
        target = resolve_ladder(plan, window)
        resting = self._client.get_open_orders()
        to_place, to_cancel = diff_orders(target, resting, window.tick_size)

        for order_id in to_cancel:
            self._client.cancel_order(order_id)
        for level in to_place:
            self._client.place_order(OrderIntent(token_id=level.token_id, price=level.price, size=level.size))
