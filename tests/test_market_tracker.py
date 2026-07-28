import json

from polymarket_mm_bot.market_tracker import (
    MarketTracker,
    WINDOW_SECONDS,
    parse_window_event,
)

REAL_EVENT_FIXTURE = {
    "slug": "btc-updown-5m-1785211500",
    "markets": [
        {
            "conditionId": "0x624ef2c097ae683c51c76d61a5dfbfbfa31509ce3cbef05496097ef0b5c0382e",
            "outcomes": json.dumps(["Up", "Down"]),
            "clobTokenIds": json.dumps([
                "87572185973009353789429361629838295092690423207939371075530216797729986720452",
                "56620820334879474729872821159638696584521013915670308978450703539419678166100",
            ]),
            "rewardsMaxSpread": 4.5,
            "rewardsMinSize": 50,
            "orderPriceMinTickSize": 0.01,
        }
    ],
}


def test_parse_window_event_extracts_fields():
    window = parse_window_event(REAL_EVENT_FIXTURE, start_ts=1785211500)
    assert window is not None
    assert window.condition_id == "0x624ef2c097ae683c51c76d61a5dfbfbfa31509ce3cbef05496097ef0b5c0382e"
    assert window.up_token_id == "87572185973009353789429361629838295092690423207939371075530216797729986720452"
    assert window.down_token_id == "56620820334879474729872821159638696584521013915670308978450703539419678166100"
    assert window.max_spread_cents == 4.5
    assert window.min_reward_size == 50.0
    assert window.tick_size == 0.01
    assert window.end_ts == 1785211500 + WINDOW_SECONDS


def test_parse_window_event_handles_empty_event():
    assert parse_window_event({}, start_ts=0) is None
    assert parse_window_event({"markets": []}, start_ts=0) is None


def test_current_window_start_rounds_down_to_5_minutes():
    tracker = MarketTracker(gamma_host="https://gamma-api.polymarket.com")
    assert tracker.current_window_start(now_ts=1785211534) == 1785211500


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_params = params
        return _FakeResponse(self._payload)


def test_fetch_window_uses_slug_convention_and_parses():
    fake_session = _FakeSession(payload=[REAL_EVENT_FIXTURE])
    tracker = MarketTracker(gamma_host="https://gamma-api.polymarket.com", _session=fake_session)

    window = tracker.fetch_window(1785211500)

    assert fake_session.last_params == {"slug": "btc-updown-5m-1785211500"}
    assert window is not None
    assert window.slug == "btc-updown-5m-1785211500"


def test_fetch_window_returns_none_for_empty_response():
    fake_session = _FakeSession(payload=[])
    tracker = MarketTracker(gamma_host="https://gamma-api.polymarket.com", _session=fake_session)
    assert tracker.fetch_window(1785211500) is None
