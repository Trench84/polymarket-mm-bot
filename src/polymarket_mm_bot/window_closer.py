from __future__ import annotations

from polymarket_mm_bot.clob_client import ClobClientProtocol
from polymarket_mm_bot.market_tracker import WindowInfo


def should_pull_quotes(now_ts: float, window_end_ts: float, pull_seconds_before_close: float) -> bool:
    return (window_end_ts - now_ts) <= pull_seconds_before_close


class WindowCloser:
    def __init__(self, client: ClobClientProtocol, pull_seconds_before_close: float) -> None:
        self._client = client
        self._pull_seconds_before_close = pull_seconds_before_close
        self._pulled_for_slug: str | None = None

    def maybe_pull_quotes(self, window: WindowInfo, now_ts: float) -> bool:
        if self._pulled_for_slug == window.slug:
            return False
        if not should_pull_quotes(now_ts, window.end_ts, self._pull_seconds_before_close):
            return False
        self._client.cancel_all()
        self._pulled_for_slug = window.slug
        return True
