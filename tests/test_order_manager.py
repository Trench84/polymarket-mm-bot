from polymarket_mm_bot.clob_client import DryRunClobClient, OrderIntent, PlacedOrder
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.order_manager import OrderManager, diff_orders, resolve_ladder
from polymarket_mm_bot.quote_engine import LadderLevel, LadderPlan

WINDOW = WindowInfo(
    slug="btc-updown-5m-1785211500",
    condition_id="0xabc",
    up_token_id="up-token",
    down_token_id="down-token",
    start_ts=1785211500,
    end_ts=1785211800,
    max_spread_cents=4.5,
    min_reward_size=1.0,
    tick_size=0.01,
)


def test_resolve_ladder_maps_up_down_to_token_ids():
    plan = LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0), LadderLevel(token="DOWN", price=0.47, size=12.0)])
    resolved = resolve_ladder(plan, WINDOW)
    assert resolved[0].token_id == "up-token"
    assert resolved[1].token_id == "down-token"


def test_diff_orders_places_missing_and_cancels_stale():
    target = resolve_ladder(
        LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)]),
        WINDOW,
    )
    resting = [PlacedOrder(order_id="o1", token_id="up-token", price=0.40, size=5.0)]  # stale: not in target

    to_place, to_cancel = diff_orders(target, resting, tick_size=0.01)

    assert to_place == target
    assert to_cancel == ["o1"]


def test_diff_orders_leaves_matching_levels_alone():
    target = resolve_ladder(
        LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)]),
        WINDOW,
    )
    resting = [PlacedOrder(order_id="o1", token_id="up-token", price=0.48, size=10.0)]  # already matches

    to_place, to_cancel = diff_orders(target, resting, tick_size=0.01)

    assert to_place == []
    assert to_cancel == []


def test_order_manager_reconcile_places_and_cancels_via_client():
    client = DryRunClobClient()
    stale = client.place_order(OrderIntent(token_id="up-token", price=0.10, size=5.0))
    manager = OrderManager(client)
    plan = LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)])

    manager.reconcile(plan, WINDOW)

    open_orders = client.get_open_orders()
    assert stale.order_id not in [o.order_id for o in open_orders]
    assert any(o.token_id == "up-token" and o.price == 0.48 for o in open_orders)
