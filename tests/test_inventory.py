import pytest

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
