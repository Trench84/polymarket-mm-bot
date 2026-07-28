from __future__ import annotations

from typing import Any

from py_clob_client.client import ClobClient


class MarketDataClient:
    """Read-only, unauthenticated CLOB market data. Safe to call in dry-run mode."""

    def __init__(self, host: str, _client: Any = None) -> None:
        self._client = _client if _client is not None else ClobClient(host)

    def get_midpoint(self, token_id: str) -> float:
        response = self._client.get_midpoint(token_id)
        return float(response["mid"])
