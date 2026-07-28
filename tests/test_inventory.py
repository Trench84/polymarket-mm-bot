import pytest

from polymarket_mm_bot.clob_client import Fill
from polymarket_mm_bot.inventory import InventoryTracker


def test_starts_flat():
    inv = InventoryTracker()
    assert inv.net_shares == 0.0
    assert inv.skew(200.0) == 0.0
    assert inv.imbalance_exceeded(200.0) is False


def test_record_fill_updates_net_shares():
    inv = InventoryTracker()
    inv.record_fill("UP", 60.0)
    inv.record_fill("DOWN", 20.0)
    assert inv.net_shares == pytest.approx(40.0)


def test_skew_positive_when_net_long_up():
    inv = InventoryTracker()
    inv.record_fill("UP", 100.0)
    assert inv.skew(200.0) == pytest.approx(0.5)


def test_skew_clamped_at_extremes():
    inv = InventoryTracker()
    inv.record_fill("UP", 1000.0)
    assert inv.skew(200.0) == pytest.approx(1.0)


def test_imbalance_exceeded_triggers_at_ceiling():
    inv = InventoryTracker()
    inv.record_fill("UP", 250.0)
    assert inv.imbalance_exceeded(200.0) is True


def test_reset_clears_position():
    inv = InventoryTracker()
    inv.record_fill("UP", 100.0)
    inv.reset()
    assert inv.net_shares == 0.0


def test_sync_from_fills_recomputes_shares_by_token_id():
    inv = InventoryTracker()
    fills = [
        Fill(token_id="up-token", size=10.0),
        Fill(token_id="down-token", size=4.0),
        Fill(token_id="up-token", size=5.0),
    ]
    inv.sync_from_fills(fills, up_token_id="up-token", down_token_id="down-token")
    assert inv.up_shares == pytest.approx(15.0)
    assert inv.down_shares == pytest.approx(4.0)


def test_sync_from_fills_overwrites_previous_state_rather_than_accumulating():
    inv = InventoryTracker()
    inv.record_fill("UP", 999.0)
    inv.sync_from_fills(
        [Fill(token_id="up-token", size=2.0)],
        up_token_id="up-token",
        down_token_id="down-token",
    )
    assert inv.up_shares == pytest.approx(2.0)
