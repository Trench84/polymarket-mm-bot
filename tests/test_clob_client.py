from polymarket_mm_bot.clob_client import DryRunClobClient, OrderIntent


def test_place_order_records_and_returns_placed_order():
    client = DryRunClobClient()
    placed = client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    assert placed.token_id == "up-token"
    assert placed.price == 0.53
    assert placed.size == 10.0
    assert placed in client.get_open_orders()
    assert client.placed_log == [OrderIntent(token_id="up-token", price=0.53, size=10.0)]


def test_cancel_order_removes_from_open_orders():
    client = DryRunClobClient()
    placed = client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    client.cancel_order(placed.order_id)
    assert client.get_open_orders() == []
    assert client.cancelled_log == [placed.order_id]


def test_cancel_all_clears_every_open_order():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    client.place_order(OrderIntent(token_id="down-token", price=0.44, size=8.0))
    client.cancel_all()
    assert client.get_open_orders() == []


def test_dry_run_get_fills_is_always_empty():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    assert client.get_fills(condition_id="0xabc", after_ts=0) == []
