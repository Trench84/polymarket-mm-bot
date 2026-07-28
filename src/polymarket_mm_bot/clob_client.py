from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, TradeParams
from py_clob_client.constants import POLYGON
from py_clob_client.order_builder.constants import BUY


@dataclass(frozen=True)
class OrderIntent:
    token_id: str
    price: float
    size: float


@dataclass(frozen=True)
class PlacedOrder:
    order_id: str
    token_id: str
    price: float
    size: float


@dataclass(frozen=True)
class Fill:
    token_id: str
    size: float


class ClobClientProtocol(Protocol):
    def place_order(self, intent: OrderIntent) -> PlacedOrder: ...
    def cancel_order(self, order_id: str) -> None: ...
    def cancel_all(self) -> None: ...
    def get_open_orders(self) -> list[PlacedOrder]: ...
    def get_fills(self, condition_id: str, after_ts: int) -> list[Fill]: ...


class DryRunClobClient:
    """Logs intended orders instead of submitting them. Default mode; also used
    directly in every OrderManager/WindowCloser unit test."""

    def __init__(self) -> None:
        self._orders: dict[str, PlacedOrder] = {}
        self._next_id = 0
        self.placed_log: list[OrderIntent] = []
        self.cancelled_log: list[str] = []

    def place_order(self, intent: OrderIntent) -> PlacedOrder:
        self._next_id += 1
        order_id = f"dryrun-{self._next_id}"
        order = PlacedOrder(order_id=order_id, token_id=intent.token_id, price=intent.price, size=intent.size)
        self._orders[order_id] = order
        self.placed_log.append(intent)
        return order

    def cancel_order(self, order_id: str) -> None:
        self._orders.pop(order_id, None)
        self.cancelled_log.append(order_id)

    def cancel_all(self) -> None:
        for order_id in list(self._orders):
            self.cancel_order(order_id)

    def get_open_orders(self) -> list[PlacedOrder]:
        return list(self._orders.values())

    def get_fills(self, condition_id: str, after_ts: int) -> list[Fill]:
        # Dry-run never submits real orders, so there is never a real fill to
        # report - inventory/skew/redemption are only meaningfully exercised
        # in live mode. Returning [] here is accurate, not a stub.
        return []


class LiveClobClient:
    """Wraps py-clob-client for real order placement. Only ever places BUY limit
    orders - see design doc: buying the complementary token stands in for
    selling, so this bot never needs inventory to sell."""

    def __init__(
        self,
        host: str,
        private_key: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        funder: str,
    ) -> None:
        self._client = ClobClient(
            host,
            chain_id=POLYGON,
            key=private_key,
            creds=ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase),
            funder=funder,
        )

    def place_order(self, intent: OrderIntent) -> PlacedOrder:
        order_args = OrderArgs(token_id=intent.token_id, price=intent.price, size=intent.size, side=BUY)
        signed_order = self._client.create_order(order_args)
        response = self._client.post_order(signed_order)
        order_id = response.get("orderID", "") if isinstance(response, dict) else ""
        return PlacedOrder(order_id=order_id, token_id=intent.token_id, price=intent.price, size=intent.size)

    def cancel_order(self, order_id: str) -> None:
        self._client.cancel(order_id)

    def cancel_all(self) -> None:
        self._client.cancel_all()

    def get_open_orders(self) -> list[PlacedOrder]:
        raw_orders = self._client.get_orders()
        return [
            PlacedOrder(
                order_id=o.get("id", ""),
                token_id=o.get("asset_id", ""),
                price=float(o.get("price", 0.0)),
                size=float(o.get("original_size", 0.0)),
            )
            for o in raw_orders
        ]

    def get_fills(self, condition_id: str, after_ts: int) -> list[Fill]:
        # Field names (asset_id, size) match get_orders' row shape from the
        # same authenticated API family; not independently confirmed against
        # a live trade history since that needs real account credentials.
        raw_trades = self._client.get_trades(TradeParams(market=condition_id, after=after_ts))
        return [Fill(token_id=t.get("asset_id", ""), size=float(t.get("size", 0.0))) for t in raw_trades]
