from __future__ import annotations

from dataclasses import dataclass

from polymarket_mm_bot.quote_engine import Token


@dataclass
class InventoryTracker:
    up_shares: float = 0.0
    down_shares: float = 0.0

    def record_fill(self, token: Token, size: float) -> None:
        if token == "UP":
            self.up_shares += size
        else:
            self.down_shares += size

    @property
    def net_shares(self) -> float:
        return self.up_shares - self.down_shares

    def skew(self, ceiling_shares: float) -> float:
        if ceiling_shares <= 0:
            return 0.0
        return min(max(self.net_shares / ceiling_shares, -1.0), 1.0)

    def imbalance_exceeded(self, ceiling_shares: float) -> bool:
        return abs(self.net_shares) >= ceiling_shares

    def reset(self) -> None:
        self.up_shares = 0.0
        self.down_shares = 0.0
