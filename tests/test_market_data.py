from polymarket_mm_bot.market_data import MarketDataClient


class _FakeUnderlyingClient:
    def __init__(self, mid: str) -> None:
        self._mid = mid

    def get_midpoint(self, token_id: str) -> dict:
        return {"mid": self._mid}


def test_get_midpoint_parses_real_response_shape():
    client = MarketDataClient(host="https://clob.polymarket.com", _client=_FakeUnderlyingClient("0.63"))
    assert client.get_midpoint("some-token-id") == 0.63
