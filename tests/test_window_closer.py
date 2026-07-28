from polymarket_mm_bot.clob_client import DryRunClobClient, OrderIntent
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.window_closer import WindowCloser, should_pull_quotes

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


def test_should_pull_quotes_false_when_far_from_close():
    assert should_pull_quotes(now_ts=1785211500, window_end_ts=1785211800, pull_seconds_before_close=8.0) is False


def test_should_pull_quotes_true_within_threshold():
    assert should_pull_quotes(now_ts=1785211793, window_end_ts=1785211800, pull_seconds_before_close=8.0) is True


def test_maybe_pull_quotes_cancels_all_once_per_window():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.48, size=10.0))
    closer = WindowCloser(client, pull_seconds_before_close=8.0)

    pulled_first = closer.maybe_pull_quotes(WINDOW, now_ts=1785211793)
    pulled_second = closer.maybe_pull_quotes(WINDOW, now_ts=1785211797)

    assert pulled_first is True
    assert pulled_second is False  # already pulled for this window's slug
    assert client.get_open_orders() == []


def test_maybe_pull_quotes_noop_before_threshold():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.48, size=10.0))
    closer = WindowCloser(client, pull_seconds_before_close=8.0)

    pulled = closer.maybe_pull_quotes(WINDOW, now_ts=1785211600)

    assert pulled is False
    assert len(client.get_open_orders()) == 1
