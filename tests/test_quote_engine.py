import pytest

from polymarket_mm_bot.quote_engine import LadderLevel, compute_ladder, floor_to_tick


def test_floor_to_tick():
    assert floor_to_tick(0.537, 0.01) == pytest.approx(0.53)
    assert floor_to_tick(0.50, 0.01) == pytest.approx(0.50)


def test_symmetric_ladder_when_balanced():
    plan = compute_ladder(
        midpoint_up=0.50,
        max_spread_cents=4.5,
        tick_size=0.01,
        min_reward_size=1.0,
        capital_usd=100.0,
        n_levels_per_side=4,
        inventory_skew=0.0,
    )
    up_cost = sum(l.price * l.size for l in plan.levels if l.token == "UP")
    down_cost = sum(l.price * l.size for l in plan.levels if l.token == "DOWN")
    assert up_cost == pytest.approx(down_cost, rel=0.05)
    assert up_cost == pytest.approx(50.0, rel=0.05)


def test_weights_favor_near_midpoint():
    plan = compute_ladder(
        midpoint_up=0.50,
        max_spread_cents=4.5,
        tick_size=0.01,
        min_reward_size=1.0,
        capital_usd=100.0,
        n_levels_per_side=4,
        inventory_skew=0.0,
    )
    up_levels = sorted((l for l in plan.levels if l.token == "UP"), key=lambda l: l.price, reverse=True)
    sizes = [l.size for l in up_levels]
    assert sizes == sorted(sizes, reverse=True)


def test_prices_within_max_spread_of_midpoint():
    plan = compute_ladder(
        midpoint_up=0.50,
        max_spread_cents=4.5,
        tick_size=0.01,
        min_reward_size=1.0,
        capital_usd=100.0,
        n_levels_per_side=4,
        inventory_skew=0.0,
    )
    for level in plan.levels:
        mid = 0.50 if level.token == "UP" else 0.50
        assert abs(mid - level.price) <= 0.045 + 1e-9


def test_skew_reduces_overexposed_side():
    plan = compute_ladder(
        midpoint_up=0.50,
        max_spread_cents=4.5,
        tick_size=0.01,
        min_reward_size=1.0,
        capital_usd=100.0,
        n_levels_per_side=4,
        inventory_skew=0.8,  # net long UP -> reduce new UP buys
    )
    up_cost = sum(l.price * l.size for l in plan.levels if l.token == "UP")
    down_cost = sum(l.price * l.size for l in plan.levels if l.token == "DOWN")
    assert up_cost < down_cost


def test_prices_respect_tick_size():
    plan = compute_ladder(
        midpoint_up=0.527,
        max_spread_cents=4.5,
        tick_size=0.01,
        min_reward_size=1.0,
        capital_usd=100.0,
        n_levels_per_side=4,
        inventory_skew=0.0,
    )
    for level in plan.levels:
        steps = level.price / 0.01
        assert steps == pytest.approx(round(steps), abs=1e-6)


def test_tiny_capital_filters_out_subminimum_levels():
    plan = compute_ladder(
        midpoint_up=0.50,
        max_spread_cents=4.5,
        tick_size=0.01,
        min_reward_size=50.0,
        capital_usd=1.0,
        n_levels_per_side=4,
        inventory_skew=0.0,
    )
    assert plan.levels == []
