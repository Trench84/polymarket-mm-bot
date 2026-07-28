import json

from polymarket_mm_bot.clob_client import Fill
from polymarket_mm_bot.dashboard_state import build_state_snapshot, write_state_snapshot
from polymarket_mm_bot.inventory import InventoryTracker
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.quote_engine import LadderLevel, LadderPlan
from polymarket_mm_bot.redemption import RedemptionRetryQueue

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


def test_snapshot_with_no_window_is_null():
    snapshot = build_state_snapshot(
        now=1785211600,
        dry_run=True,
        window=None,
        midpoint_up=None,
        skew=0.0,
        inventory=InventoryTracker(),
        plan=None,
        last_redemption=None,
        retry_queue=RedemptionRetryQueue(max_attempts=5),
        recent_events=[],
    )
    assert snapshot["window"] is None
    assert snapshot["midpoint_up"] is None
    assert snapshot["dry_run"] is True


def test_snapshot_window_fields_and_seconds_remaining():
    snapshot = build_state_snapshot(
        now=1785211790,
        dry_run=False,
        window=WINDOW,
        midpoint_up=0.62,
        skew=0.1,
        inventory=InventoryTracker(),
        plan=None,
        last_redemption=None,
        retry_queue=RedemptionRetryQueue(max_attempts=5),
        recent_events=[],
    )
    assert snapshot["window"]["slug"] == "btc-updown-5m-1785211500"
    assert snapshot["window"]["end_ts"] == 1785211800
    assert snapshot["window"]["seconds_remaining"] == 10


def test_snapshot_seconds_remaining_clamped_at_zero_past_close():
    snapshot = build_state_snapshot(
        now=1785211900,
        dry_run=False,
        window=WINDOW,
        midpoint_up=0.5,
        skew=0.0,
        inventory=InventoryTracker(),
        plan=None,
        last_redemption=None,
        retry_queue=RedemptionRetryQueue(max_attempts=5),
        recent_events=[],
    )
    assert snapshot["window"]["seconds_remaining"] == 0


def test_snapshot_inventory_fields():
    inventory = InventoryTracker()
    inventory.sync_from_fills(
        [Fill(token_id="up-token", size=12.0), Fill(token_id="down-token", size=4.0)],
        up_token_id="up-token",
        down_token_id="down-token",
    )
    snapshot = build_state_snapshot(
        now=1785211600,
        dry_run=True,
        window=WINDOW,
        midpoint_up=0.5,
        skew=0.2,
        inventory=inventory,
        plan=None,
        last_redemption=None,
        retry_queue=RedemptionRetryQueue(max_attempts=5),
        recent_events=[],
    )
    assert snapshot["inventory"] == {"up_shares": 12.0, "down_shares": 4.0, "net_shares": 8.0}


def test_snapshot_ladder_levels_serialized():
    plan = LadderPlan(
        levels=[
            LadderLevel(token="UP", price=0.48, size=10.0),
            LadderLevel(token="DOWN", price=0.47, size=12.0),
        ]
    )
    snapshot = build_state_snapshot(
        now=1785211600,
        dry_run=True,
        window=WINDOW,
        midpoint_up=0.5,
        skew=0.0,
        inventory=InventoryTracker(),
        plan=plan,
        last_redemption=None,
        retry_queue=RedemptionRetryQueue(max_attempts=5),
        recent_events=[],
    )
    assert snapshot["ladder"]["levels"] == [
        {"token": "UP", "price": 0.48, "size": 10.0},
        {"token": "DOWN", "price": 0.47, "size": 12.0},
    ]
    assert snapshot["ladder"]["total_cost_usd"] == plan.total_cost_usd


def test_snapshot_redemption_fields():
    queue = RedemptionRetryQueue(max_attempts=2)
    queue.record_failure("0xdead")
    queue.record_failure("0xdead")  # now exhausted
    last_redemption = {"slug": "btc-updown-5m-1785211200", "tx_hash": "0xfeed", "at": 1785211550}

    snapshot = build_state_snapshot(
        now=1785211600,
        dry_run=True,
        window=WINDOW,
        midpoint_up=0.5,
        skew=0.0,
        inventory=InventoryTracker(),
        plan=None,
        last_redemption=last_redemption,
        retry_queue=queue,
        recent_events=[],
    )
    assert snapshot["redemption"]["last"] == last_redemption
    assert snapshot["redemption"]["pending_count"] == 0
    assert snapshot["redemption"]["exhausted"] == ["0xdead"]


def test_snapshot_is_json_serializable():
    plan = LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)])
    snapshot = build_state_snapshot(
        now=1785211600,
        dry_run=True,
        window=WINDOW,
        midpoint_up=0.5,
        skew=0.0,
        inventory=InventoryTracker(),
        plan=plan,
        last_redemption=None,
        retry_queue=RedemptionRetryQueue(max_attempts=5),
        recent_events=[{"at": 1785211590, "message": "window rolled over"}],
    )
    json.dumps(snapshot)  # must not raise


def test_write_state_snapshot_round_trips(tmp_path):
    path = tmp_path / "nested" / "state.json"
    snapshot = {"generated_at": 123, "dry_run": True}
    write_state_snapshot(path, snapshot)
    assert json.loads(path.read_text()) == snapshot


def test_write_state_snapshot_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "state.json"
    write_state_snapshot(path, {"a": 1})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
