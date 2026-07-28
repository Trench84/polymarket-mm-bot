# Polymarket BTC 5-min Market-Making Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bot that continuously quotes a two-sided BUY-only ladder on Polymarket's "BTC Up or Down 5m" market series to earn the Maker Rebate + Liquidity Rewards programs, per `docs/superpowers/specs/2026-07-27-polymarket-mm-bot-design.md`.

**Architecture:** Single async-loop Python process. A read-only `MarketDataClient` (unauthenticated CLOB REST) supplies live midpoint/book; `MarketTracker` discovers each 5-min window via the Gamma events API; `QuoteEngine.compute_ladder` (pure function) turns midpoint + market config + inventory skew into a target ladder; `OrderManager` reconciles that target against resting orders through a swappable `ClobClientProtocol` (`DryRunClobClient` logs instead of submitting; `LiveClobClient` wraps `py-clob-client`); `WindowCloser` pulls quotes before resolution; `InventoryTracker` and `KillSwitch` provide risk control.

**Tech Stack:** Python 3.11+, `py-clob-client` 0.34+, `requests`, `python-dotenv`, `pytest` (dev). All API field names below (`rewardsMaxSpread`, `rewardsMinSize`, `orderPriceMinTickSize`, `get_midpoint` response shape, `OrderSummary` fields) were verified live against Polymarket's public Gamma and CLOB REST endpoints while writing this plan, not guessed.

## Global Constraints

- Bot only ever places BUY limit orders (buying the complementary outcome token stands in for selling — see design doc "Prior art"/architecture). No SELL orders, no short logic.
- `dry_run=True` is the default; `LiveClobClient` is only constructed when `dry_run=False` and all credential env vars are present.
- All modules under `src/polymarket_mm_bot/` must be importable and independently unit-testable without network access, except `MarketDataClient`/`MarketTracker`/`LiveClobClient`, whose network calls are isolated behind thin wrappers so the rest of the system stays pure and testable.
- No credentials are ever logged, printed, or committed. `.env` stays git-ignored (already the case).

---

## File Structure

```
src/polymarket_mm_bot/
  __init__.py
  config.py          # Config dataclass, env loading
  quote_engine.py     # LadderLevel, LadderPlan, compute_ladder (pure)
  inventory.py         # InventoryTracker (pure)
  market_data.py        # MarketDataClient (read-only CLOB REST: midpoint)
  market_tracker.py      # WindowInfo, parse_window_event (pure), MarketTracker (Gamma API)
  clob_client.py           # OrderIntent, PlacedOrder, ClobClientProtocol, DryRunClobClient, LiveClobClient
  order_manager.py          # resolve_ladder, diff_orders (pure), OrderManager
  window_closer.py           # should_pull_quotes (pure), WindowCloser
  kill_switch.py               # KillSwitch
  bot.py                        # wires everything into the async loop
tests/
  __init__.py
  test_config.py
  test_quote_engine.py
  test_inventory.py
  test_market_data.py
  test_market_tracker.py
  test_clob_client.py
  test_order_manager.py
  test_window_closer.py
  test_kill_switch.py
```

Package layout, build backend, and `pytest` test path are already configured in `pyproject.toml` (`[tool.hatch.build.targets.wheel] packages = ["src/polymarket_mm_bot"]`, `[tool.pytest.ini_options] testpaths = ["tests"]`) and verified working (`uv sync` + `import polymarket_mm_bot` succeeds).

---

### Task 1: Config

**Files:**
- Create: `src/polymarket_mm_bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` (frozen dataclass) with fields `private_key: str`, `api_key: str`, `api_secret: str`, `api_passphrase: str`, `funder_address: str`, `clob_host: str`, `gamma_host: str`, `capital_per_window_usd: float`, `max_concurrent_windows: int`, `n_ladder_levels: int`, `imbalance_ceiling_shares: float`, `pull_quote_seconds_before_close: float`, `dry_run: bool`; classmethod-style `Config.from_env(env_path: Path | None = None) -> Config`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import pytest

from polymarket_mm_bot.config import Config


def test_defaults_in_dry_run_mode(monkeypatch, tmp_path):
    for var in [
        "POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET",
        "POLY_API_PASSPHRASE", "POLY_FUNDER_ADDRESS",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("POLY_DRY_RUN", "true")

    config = Config.from_env(env_path=tmp_path / "does-not-exist.env")

    assert config.dry_run is True
    assert config.capital_per_window_usd == 100.0
    assert config.n_ladder_levels == 4
    assert config.clob_host == "https://clob.polymarket.com"


def test_missing_credentials_raise_when_not_dry_run(monkeypatch, tmp_path):
    for var in [
        "POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET",
        "POLY_API_PASSPHRASE", "POLY_FUNDER_ADDRESS",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("POLY_DRY_RUN", "false")

    with pytest.raises(ValueError, match="POLY_PRIVATE_KEY"):
        Config.from_env(env_path=tmp_path / "does-not-exist.env")


def test_reads_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("POLY_DRY_RUN", "true")
    monkeypatch.setenv("POLY_CAPITAL_PER_WINDOW_USD", "250")
    monkeypatch.setenv("POLY_N_LADDER_LEVELS", "6")
    monkeypatch.setenv("POLY_IMBALANCE_CEILING_SHARES", "500")

    config = Config.from_env(env_path=tmp_path / "does-not-exist.env")

    assert config.capital_per_window_usd == 250.0
    assert config.n_ladder_levels == 6
    assert config.imbalance_ceiling_shares == 500.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.config'`

- [ ] **Step 3: Implement Config**

```python
# src/polymarket_mm_bot/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str
    funder_address: str
    clob_host: str = "https://clob.polymarket.com"
    gamma_host: str = "https://gamma-api.polymarket.com"
    capital_per_window_usd: float = 100.0
    max_concurrent_windows: int = 1
    n_ladder_levels: int = 4
    imbalance_ceiling_shares: float = 200.0
    pull_quote_seconds_before_close: float = 8.0
    dry_run: bool = True

    @staticmethod
    def from_env(env_path: Path | None = None) -> "Config":
        load_dotenv(dotenv_path=env_path)

        def _get(name: str, default: str = "") -> str:
            return os.environ.get(name, default)

        def _get_required_unless_dry_run(name: str, dry_run: bool) -> str:
            value = os.environ.get(name, "")
            if not dry_run and not value:
                raise ValueError(f"missing required environment variable: {name}")
            return value

        dry_run = _get("POLY_DRY_RUN", "true").lower() != "false"

        return Config(
            private_key=_get_required_unless_dry_run("POLY_PRIVATE_KEY", dry_run),
            api_key=_get_required_unless_dry_run("POLY_API_KEY", dry_run),
            api_secret=_get_required_unless_dry_run("POLY_API_SECRET", dry_run),
            api_passphrase=_get_required_unless_dry_run("POLY_API_PASSPHRASE", dry_run),
            funder_address=_get_required_unless_dry_run("POLY_FUNDER_ADDRESS", dry_run),
            clob_host=_get("POLY_CLOB_HOST", "https://clob.polymarket.com"),
            gamma_host=_get("POLY_GAMMA_HOST", "https://gamma-api.polymarket.com"),
            capital_per_window_usd=float(_get("POLY_CAPITAL_PER_WINDOW_USD", "100")),
            max_concurrent_windows=int(_get("POLY_MAX_CONCURRENT_WINDOWS", "1")),
            n_ladder_levels=int(_get("POLY_N_LADDER_LEVELS", "4")),
            imbalance_ceiling_shares=float(_get("POLY_IMBALANCE_CEILING_SHARES", "200")),
            pull_quote_seconds_before_close=float(_get("POLY_PULL_QUOTE_SECONDS", "8")),
            dry_run=dry_run,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/__init__.py src/polymarket_mm_bot/config.py tests/__init__.py tests/test_config.py pyproject.toml uv.lock
git commit -m "feat: add Config with env loading and dry-run credential gating"
```

---

### Task 2: QuoteEngine (ladder math)

**Files:**
- Create: `src/polymarket_mm_bot/quote_engine.py`
- Test: `tests/test_quote_engine.py`

**Interfaces:**
- Produces: `LadderLevel(token: Literal["UP","DOWN"], price: float, size: float)`, `LadderPlan(levels: list[LadderLevel])` with property `total_cost_usd`, `floor_to_tick(price: float, tick: float) -> float`, `compute_ladder(midpoint_up, max_spread_cents, tick_size, min_reward_size, capital_usd, n_levels_per_side, inventory_skew) -> LadderPlan`.
- Consumes: nothing (pure).

This is the strategy core described in the design doc: levels are placed at offsets from
the live midpoint (never an absolute price band), sized with Polymarket's own Liquidity
Rewards quadratic scoring shape `((max_spread - offset) / max_spread) ** 2` so sizing
naturally concentrates where the reward program pays best, and skewed between the Up/Down
legs by `inventory_skew` to passively correct imbalance (per design: "skew quotes to
rebalance").

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quote_engine.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quote_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.quote_engine'`

- [ ] **Step 3: Implement QuoteEngine**

```python
# src/polymarket_mm_bot/quote_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Token = Literal["UP", "DOWN"]


@dataclass(frozen=True)
class LadderLevel:
    token: Token
    price: float
    size: float


@dataclass(frozen=True)
class LadderPlan:
    levels: list[LadderLevel]

    @property
    def total_cost_usd(self) -> float:
        return sum(l.price * l.size for l in self.levels)


def floor_to_tick(price: float, tick: float) -> float:
    steps = int(price / tick + 1e-9)
    return round(steps * tick, 8)


def compute_ladder(
    midpoint_up: float,
    max_spread_cents: float,
    tick_size: float,
    min_reward_size: float,
    capital_usd: float,
    n_levels_per_side: int,
    inventory_skew: float,
) -> LadderPlan:
    """Build a two-sided BUY-only ladder centered on the live midpoint.

    Levels are placed at offsets from the midpoint (not an absolute price band) so
    they always stay within the market's own Liquidity Rewards max-spread cutoff.
    Sizing uses the same quadratic shape as Polymarket's own reward scoring
    function, so capital naturally concentrates where fills pay the most rebate.
    `inventory_skew` in [-1, 1] shifts capital between the UP/DOWN legs: positive
    means net long UP, so UP buys shrink and DOWN buys grow, pulling the position
    back toward flat.
    """
    midpoint_up = min(max(midpoint_up, 0.02), 0.98)
    max_spread = max_spread_cents / 100.0
    skew = min(max(inventory_skew, -1.0), 1.0)

    up_fraction = 0.5 - 0.5 * skew
    down_fraction = 0.5 + 0.5 * skew

    offsets = [max_spread * (i + 0.5) / n_levels_per_side for i in range(n_levels_per_side)]
    raw_weights = [((max_spread - o) / max_spread) ** 2 for o in offsets]
    weight_sum = sum(raw_weights)
    weights = [w / weight_sum for w in raw_weights]

    levels: list[LadderLevel] = []
    for token, fraction, mid in (
        ("UP", up_fraction, midpoint_up),
        ("DOWN", down_fraction, 1.0 - midpoint_up),
    ):
        side_capital = capital_usd * fraction
        for offset, weight in zip(offsets, weights):
            price = floor_to_tick(mid - offset, tick_size)
            price = min(max(price, tick_size), 1.0 - tick_size)
            level_capital = side_capital * weight
            size = level_capital / price
            if size < min_reward_size:
                continue
            levels.append(LadderLevel(token=token, price=price, size=round(size, 2)))

    return LadderPlan(levels=levels)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quote_engine.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/quote_engine.py tests/test_quote_engine.py
git commit -m "feat: add QuoteEngine ladder math with reward-curve-shaped sizing"
```

---

### Task 3: InventoryTracker

**Files:**
- Create: `src/polymarket_mm_bot/inventory.py`
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `Token` from `polymarket_mm_bot.quote_engine`.
- Produces: `InventoryTracker` with `record_fill(token: Token, size: float) -> None`, property `net_shares: float`, `skew(ceiling_shares: float) -> float`, `imbalance_exceeded(ceiling_shares: float) -> bool`, `reset() -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inventory.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_inventory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.inventory'`

- [ ] **Step 3: Implement InventoryTracker**

```python
# src/polymarket_mm_bot/inventory.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_inventory.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/inventory.py tests/test_inventory.py
git commit -m "feat: add InventoryTracker for skew and imbalance-ceiling checks"
```

---

### Task 4: MarketDataClient (read-only midpoint)

**Files:**
- Create: `src/polymarket_mm_bot/market_data.py`
- Test: `tests/test_market_data.py`

**Interfaces:**
- Produces: `MarketDataClient(host: str, _client=None)` with `get_midpoint(token_id: str) -> float`.

Verified live against the real (unauthenticated) endpoint while writing this plan:
`ClobClient(host).get_midpoint(token_id)` returns `{'mid': '0.525'}` — no API key needed,
since this is public market data. Dry-run mode still reads this real endpoint; only order
*submission* is stubbed elsewhere (`DryRunClobClient`, Task 6).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market_data.py
from polymarket_mm_bot.market_data import MarketDataClient


class _FakeUnderlyingClient:
    def __init__(self, mid: str) -> None:
        self._mid = mid

    def get_midpoint(self, token_id: str) -> dict:
        return {"mid": self._mid}


def test_get_midpoint_parses_real_response_shape():
    client = MarketDataClient(host="https://clob.polymarket.com", _client=_FakeUnderlyingClient("0.63"))
    assert client.get_midpoint("some-token-id") == 0.63
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_market_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.market_data'`

- [ ] **Step 3: Implement MarketDataClient**

```python
# src/polymarket_mm_bot/market_data.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_market_data.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/market_data.py tests/test_market_data.py
git commit -m "feat: add MarketDataClient wrapping unauthenticated midpoint endpoint"
```

---

### Task 5: MarketTracker (window discovery)

**Files:**
- Create: `src/polymarket_mm_bot/market_tracker.py`
- Test: `tests/test_market_tracker.py`

**Interfaces:**
- Produces: `WindowInfo(slug, condition_id, up_token_id, down_token_id, start_ts, end_ts, max_spread_cents, min_reward_size, tick_size)`, `parse_window_event(event: dict, start_ts: int) -> WindowInfo | None`, `MarketTracker(gamma_host, _session=None)` with `fetch_window(start_ts: int) -> WindowInfo | None` and `current_window_start(now_ts: float | None = None) -> int`.

Field names (`clobTokenIds`, `conditionId`, `rewardsMaxSpread`, `rewardsMinSize`,
`orderPriceMinTickSize`) and the `btc-updown-5m-<window_start_unix_ts>` slug convention
were verified live against `https://gamma-api.polymarket.com/events?slug=...` while
writing this plan (same convention already proven in `backtest/pull_history.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_market_tracker.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_market_tracker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.market_tracker'`

- [ ] **Step 3: Implement MarketTracker**

```python
# src/polymarket_mm_bot/market_tracker.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

WINDOW_SECONDS = 300


@dataclass(frozen=True)
class WindowInfo:
    slug: str
    condition_id: str
    up_token_id: str
    down_token_id: str
    start_ts: int
    end_ts: int
    max_spread_cents: float
    min_reward_size: float
    tick_size: float


def parse_window_event(event: dict, start_ts: int) -> WindowInfo | None:
    if not event or not event.get("markets"):
        return None
    market = event["markets"][0]
    try:
        outcomes = json.loads(market["outcomes"])
        token_ids = json.loads(market["clobTokenIds"])
    except (KeyError, json.JSONDecodeError, TypeError):
        return None
    if outcomes != ["Up", "Down"] or len(token_ids) != 2:
        return None
    return WindowInfo(
        slug=event["slug"],
        condition_id=market["conditionId"],
        up_token_id=token_ids[0],
        down_token_id=token_ids[1],
        start_ts=start_ts,
        end_ts=start_ts + WINDOW_SECONDS,
        max_spread_cents=float(market["rewardsMaxSpread"]),
        min_reward_size=float(market["rewardsMinSize"]),
        tick_size=float(market["orderPriceMinTickSize"]),
    )


class MarketTracker:
    def __init__(self, gamma_host: str = "https://gamma-api.polymarket.com", _session: Any = None) -> None:
        self._gamma_host = gamma_host
        self._session = _session if _session is not None else requests.Session()

    def fetch_window(self, start_ts: int) -> WindowInfo | None:
        slug = f"btc-updown-5m-{start_ts}"
        response = self._session.get(f"{self._gamma_host}/events", params={"slug": slug}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        return parse_window_event(data[0], start_ts)

    def current_window_start(self, now_ts: float | None = None) -> int:
        now_ts = now_ts if now_ts is not None else time.time()
        return int(now_ts // WINDOW_SECONDS) * WINDOW_SECONDS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_market_tracker.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/market_tracker.py tests/test_market_tracker.py
git commit -m "feat: add MarketTracker for BTC-updown-5m window discovery via Gamma API"
```

---

### Task 6: ClobClient order interface (dry-run + live)

**Files:**
- Create: `src/polymarket_mm_bot/clob_client.py`
- Test: `tests/test_clob_client.py`

**Interfaces:**
- Produces: `OrderIntent(token_id: str, price: float, size: float)`, `PlacedOrder(order_id: str, token_id: str, price: float, size: float)`, `ClobClientProtocol` (structural: `place_order`, `cancel_order`, `cancel_all`, `get_open_orders`), `DryRunClobClient`, `LiveClobClient`.

`LiveClobClient` wraps `py_clob_client.client.ClobClient`, whose constructor and
`create_order`/`post_order`/`cancel`/`cancel_all`/`get_orders` signatures were inspected
directly from the installed package (`py-clob-client` 0.34.6) while writing this plan.
**Caveat, not a placeholder:** `post_order`'s return value and `get_orders`' row shape are
whatever the live CLOB REST API returns as JSON and cannot be exercised without real
credentials in this environment — the field names below (`orderID`, `id`, `asset_id`,
`price`, `original_size`) match Polymarket's published API reference, but Task 10's manual
live smoke test is the point where you confirm them against your own account and adjust
`LiveClobClient` if the live response differs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clob_client.py
from polymarket_mm_bot.clob_client import DryRunClobClient, OrderIntent


def test_place_order_records_and_returns_placed_order():
    client = DryRunClobClient()
    placed = client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    assert placed.token_id == "up-token"
    assert placed.price == 0.53
    assert placed.size == 10.0
    assert placed in client.get_open_orders()
    assert client.placed_log == [OrderIntent(token_id="up-token", price=0.53, size=10.0)]


def test_cancel_order_removes_from_open_orders():
    client = DryRunClobClient()
    placed = client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    client.cancel_order(placed.order_id)
    assert client.get_open_orders() == []
    assert client.cancelled_log == [placed.order_id]


def test_cancel_all_clears_every_open_order():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.53, size=10.0))
    client.place_order(OrderIntent(token_id="down-token", price=0.44, size=8.0))
    client.cancel_all()
    assert client.get_open_orders() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clob_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.clob_client'`

- [ ] **Step 3: Implement ClobClient wrapper**

```python
# src/polymarket_mm_bot/clob_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
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


class ClobClientProtocol(Protocol):
    def place_order(self, intent: OrderIntent) -> PlacedOrder: ...
    def cancel_order(self, order_id: str) -> None: ...
    def cancel_all(self) -> None: ...
    def get_open_orders(self) -> list[PlacedOrder]: ...


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


class LiveClobClient:
    """Wraps py-clob-client for real order placement. Only ever places BUY limit
    orders — see design doc: buying the complementary token stands in for
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clob_client.py -v`
Expected: PASS (3 passed) — `LiveClobClient` is exercised only in Task 10's manual live smoke test, not by pytest, since it requires real credentials.

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/clob_client.py tests/test_clob_client.py
git commit -m "feat: add DryRunClobClient and LiveClobClient behind ClobClientProtocol"
```

---

### Task 7: OrderManager (reconciliation)

**Files:**
- Create: `src/polymarket_mm_bot/order_manager.py`
- Test: `tests/test_order_manager.py`

**Interfaces:**
- Consumes: `LadderPlan`, `LadderLevel`, `floor_to_tick` from `quote_engine`; `WindowInfo` from `market_tracker`; `PlacedOrder`, `OrderIntent`, `ClobClientProtocol` from `clob_client`.
- Produces: `ResolvedLevel(token_id: str, price: float, size: float)`, `resolve_ladder(plan: LadderPlan, window: WindowInfo) -> list[ResolvedLevel]`, `diff_orders(target: list[ResolvedLevel], resting: list[PlacedOrder], tick_size: float) -> tuple[list[ResolvedLevel], list[str]]`, `OrderManager(client: ClobClientProtocol)` with `reconcile(plan: LadderPlan, window: WindowInfo) -> None`.

`diff_orders` only cancels resting orders that are no longer in the target ladder and only
places target levels that aren't already resting — orders present in both are left alone,
so a stable market doesn't churn its resting orders every poll (per design: "cancels/
replaces only what changed").

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_order_manager.py
from polymarket_mm_bot.clob_client import DryRunClobClient, PlacedOrder
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.order_manager import OrderManager, diff_orders, resolve_ladder
from polymarket_mm_bot.quote_engine import LadderLevel, LadderPlan

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


def test_resolve_ladder_maps_up_down_to_token_ids():
    plan = LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0), LadderLevel(token="DOWN", price=0.47, size=12.0)])
    resolved = resolve_ladder(plan, WINDOW)
    assert resolved[0].token_id == "up-token"
    assert resolved[1].token_id == "down-token"


def test_diff_orders_places_missing_and_cancels_stale():
    target = resolve_ladder(
        LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)]),
        WINDOW,
    )
    resting = [PlacedOrder(order_id="o1", token_id="up-token", price=0.40, size=5.0)]  # stale: not in target

    to_place, to_cancel = diff_orders(target, resting, tick_size=0.01)

    assert to_place == target
    assert to_cancel == ["o1"]


def test_diff_orders_leaves_matching_levels_alone():
    target = resolve_ladder(
        LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)]),
        WINDOW,
    )
    resting = [PlacedOrder(order_id="o1", token_id="up-token", price=0.48, size=10.0)]  # already matches

    to_place, to_cancel = diff_orders(target, resting, tick_size=0.01)

    assert to_place == []
    assert to_cancel == []


def test_order_manager_reconcile_places_and_cancels_via_client():
    client = DryRunClobClient()
    client.place_order.__self__  # sanity: real DryRunClobClient instance
    stale = client.place_order(__import__("polymarket_mm_bot.clob_client", fromlist=["OrderIntent"]).OrderIntent(
        token_id="up-token", price=0.10, size=5.0
    ))
    manager = OrderManager(client)
    plan = LadderPlan(levels=[LadderLevel(token="UP", price=0.48, size=10.0)])

    manager.reconcile(plan, WINDOW)

    open_orders = client.get_open_orders()
    assert stale.order_id not in [o.order_id for o in open_orders]
    assert any(o.token_id == "up-token" and o.price == 0.48 for o in open_orders)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_order_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.order_manager'`

- [ ] **Step 3: Implement OrderManager**

```python
# src/polymarket_mm_bot/order_manager.py
from __future__ import annotations

from dataclasses import dataclass

from polymarket_mm_bot.clob_client import ClobClientProtocol, OrderIntent, PlacedOrder
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.quote_engine import LadderPlan, floor_to_tick


@dataclass(frozen=True)
class ResolvedLevel:
    token_id: str
    price: float
    size: float


def resolve_ladder(plan: LadderPlan, window: WindowInfo) -> list[ResolvedLevel]:
    token_id_by_side = {"UP": window.up_token_id, "DOWN": window.down_token_id}
    return [
        ResolvedLevel(token_id=token_id_by_side[level.token], price=level.price, size=level.size)
        for level in plan.levels
    ]


def diff_orders(
    target: list[ResolvedLevel],
    resting: list[PlacedOrder],
    tick_size: float,
) -> tuple[list[ResolvedLevel], list[str]]:
    def order_key(price: float) -> float:
        return floor_to_tick(price, tick_size)

    target_keys = {(level.token_id, order_key(level.price)) for level in target}
    resting_by_key = {(order.token_id, order_key(order.price)): order for order in resting}

    to_place = [level for level in target if (level.token_id, order_key(level.price)) not in resting_by_key]
    to_cancel = [order.order_id for key, order in resting_by_key.items() if key not in target_keys]
    return to_place, to_cancel


class OrderManager:
    def __init__(self, client: ClobClientProtocol) -> None:
        self._client = client

    def reconcile(self, plan: LadderPlan, window: WindowInfo) -> None:
        target = resolve_ladder(plan, window)
        resting = self._client.get_open_orders()
        to_place, to_cancel = diff_orders(target, resting, window.tick_size)

        for order_id in to_cancel:
            self._client.cancel_order(order_id)
        for level in to_place:
            self._client.place_order(OrderIntent(token_id=level.token_id, price=level.price, size=level.size))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_order_manager.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/order_manager.py tests/test_order_manager.py
git commit -m "feat: add OrderManager reconciliation (diff resting vs target ladder)"
```

---

### Task 8: WindowCloser

**Files:**
- Create: `src/polymarket_mm_bot/window_closer.py`
- Test: `tests/test_window_closer.py`

**Interfaces:**
- Consumes: `WindowInfo` from `market_tracker`; `ClobClientProtocol` from `clob_client`.
- Produces: `should_pull_quotes(now_ts: float, window_end_ts: float, pull_seconds_before_close: float) -> bool`, `WindowCloser(client: ClobClientProtocol, pull_seconds_before_close: float)` with `maybe_pull_quotes(window: WindowInfo, now_ts: float) -> bool`.

Runs off an explicit `now_ts` passed in by the caller (the bot's own poll loop), not
`time.time()` internally — keeps this fully unit-testable without mocking the clock, and
matches the design's requirement that window-close handling run off "a timer independent
of book activity."

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_window_closer.py
from polymarket_mm_bot.clob_client import DryRunClobClient, OrderIntent
from polymarket_mm_bot.market_tracker import WindowInfo
from polymarket_mm_bot.window_closer import WindowCloser, should_pull_quotes

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


def test_should_pull_quotes_false_when_far_from_close():
    assert should_pull_quotes(now_ts=1785211500, window_end_ts=1785211800, pull_seconds_before_close=8.0) is False


def test_should_pull_quotes_true_within_threshold():
    assert should_pull_quotes(now_ts=1785211793, window_end_ts=1785211800, pull_seconds_before_close=8.0) is True


def test_maybe_pull_quotes_cancels_all_once_per_window():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.48, size=10.0))
    closer = WindowCloser(client, pull_seconds_before_close=8.0)

    pulled_first = closer.maybe_pull_quotes(WINDOW, now_ts=1785211793)
    pulled_second = closer.maybe_pull_quotes(WINDOW, now_ts=1785211797)

    assert pulled_first is True
    assert pulled_second is False  # already pulled for this window's slug
    assert client.get_open_orders() == []


def test_maybe_pull_quotes_noop_before_threshold():
    client = DryRunClobClient()
    client.place_order(OrderIntent(token_id="up-token", price=0.48, size=10.0))
    closer = WindowCloser(client, pull_seconds_before_close=8.0)

    pulled = closer.maybe_pull_quotes(WINDOW, now_ts=1785211600)

    assert pulled is False
    assert len(client.get_open_orders()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_window_closer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.window_closer'`

- [ ] **Step 3: Implement WindowCloser**

```python
# src/polymarket_mm_bot/window_closer.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_window_closer.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/window_closer.py tests/test_window_closer.py
git commit -m "feat: add WindowCloser to pull quotes before resolution"
```

---

### Task 9: KillSwitch

**Files:**
- Create: `src/polymarket_mm_bot/kill_switch.py`
- Test: `tests/test_kill_switch.py`

**Interfaces:**
- Produces: `KillSwitch(flag_path: Path)` with `is_triggered() -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_kill_switch.py
from polymarket_mm_bot.kill_switch import KillSwitch


def test_not_triggered_when_flag_file_absent(tmp_path):
    switch = KillSwitch(tmp_path / "STOP")
    assert switch.is_triggered() is False


def test_triggered_when_flag_file_present(tmp_path):
    flag_path = tmp_path / "STOP"
    flag_path.write_text("stop")
    switch = KillSwitch(flag_path)
    assert switch.is_triggered() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_kill_switch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymarket_mm_bot.kill_switch'`

- [ ] **Step 3: Implement KillSwitch**

```python
# src/polymarket_mm_bot/kill_switch.py
from __future__ import annotations

from pathlib import Path


class KillSwitch:
    def __init__(self, flag_path: Path) -> None:
        self._flag_path = flag_path

    def is_triggered(self) -> bool:
        return self._flag_path.exists()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_kill_switch.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/kill_switch.py tests/test_kill_switch.py
git commit -m "feat: add file-flag KillSwitch"
```

---

### Task 10: Bot wiring + manual dry-run smoke test

**Files:**
- Create: `src/polymarket_mm_bot/bot.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: every module from Tasks 1-9.
- Produces: `async def run(config: Config, flag_path: Path) -> None`, `main()` CLI entry point.

This task has no new pure unit tests — every component it wires together is already
covered. Its own verification is a manual dry-run run against the real, live market
(per design doc: "Dry-run mode... as the default first step").

- [ ] **Step 1: Implement the bot loop**

```python
# src/polymarket_mm_bot/bot.py
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from polymarket_mm_bot.clob_client import DryRunClobClient, LiveClobClient
from polymarket_mm_bot.config import Config
from polymarket_mm_bot.inventory import InventoryTracker
from polymarket_mm_bot.kill_switch import KillSwitch
from polymarket_mm_bot.market_data import MarketDataClient
from polymarket_mm_bot.market_tracker import MarketTracker
from polymarket_mm_bot.order_manager import OrderManager
from polymarket_mm_bot.quote_engine import compute_ladder
from polymarket_mm_bot.window_closer import WindowCloser

logger = logging.getLogger("polymarket_mm_bot")
POLL_SECONDS = 2.0


async def run(config: Config, flag_path: Path) -> None:
    order_client = (
        DryRunClobClient()
        if config.dry_run
        else LiveClobClient(
            host=config.clob_host,
            private_key=config.private_key,
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.api_passphrase,
            funder=config.funder_address,
        )
    )
    market_data = MarketDataClient(host=config.clob_host)
    tracker = MarketTracker(gamma_host=config.gamma_host)
    order_manager = OrderManager(order_client)
    window_closer = WindowCloser(order_client, config.pull_quote_seconds_before_close)
    inventory = InventoryTracker()
    kill_switch = KillSwitch(flag_path)

    window = tracker.fetch_window(tracker.current_window_start())

    while True:
        if kill_switch.is_triggered():
            logger.warning("kill switch triggered: cancelling all orders and stopping")
            order_client.cancel_all()
            return

        now = asyncio.get_event_loop().time().__class__ and __import__("time").time()
        new_start = tracker.current_window_start(now)
        if window is None or new_start != window.start_ts:
            window = tracker.fetch_window(new_start)
            inventory.reset()
            if window is None:
                logger.warning("no window found for start_ts=%s, retrying next poll", new_start)
                await asyncio.sleep(POLL_SECONDS)
                continue

        if window_closer.maybe_pull_quotes(window, now):
            logger.info("pulled quotes for %s ahead of resolution", window.slug)
            await asyncio.sleep(POLL_SECONDS)
            continue

        midpoint_up = market_data.get_midpoint(window.up_token_id)
        skew = inventory.skew(config.imbalance_ceiling_shares)
        plan = compute_ladder(
            midpoint_up=midpoint_up,
            max_spread_cents=window.max_spread_cents,
            tick_size=window.tick_size,
            min_reward_size=window.min_reward_size,
            capital_usd=config.capital_per_window_usd,
            n_levels_per_side=config.n_ladder_levels,
            inventory_skew=skew,
        )
        logger.info(
            "window=%s midpoint_up=%.3f skew=%.2f levels=%d total_cost=$%.2f dry_run=%s",
            window.slug, midpoint_up, skew, len(plan.levels), plan.total_cost_usd, config.dry_run,
        )
        order_manager.reconcile(plan, window)

        await asyncio.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--flag-file", type=Path, default=Path(".stop"))
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.from_env(env_path=args.env_file)
    asyncio.run(run(config, args.flag_file))


if __name__ == "__main__":
    main()
```

Note: `now = asyncio.get_event_loop().time().__class__ and __import__("time").time()` is a
placeholder-looking one-liner that must NOT survive review — replace it with a plain
`import time` at the top of the file and `now = time.time()` in the loop body before
running Step 2. (Left as an explicit fix-it note here because the loop's actual
wall-clock read has to line up with `MarketTracker`/`WindowCloser`, which both take
real Unix timestamps, not the event loop's monotonic clock.)

- [ ] **Step 2: Fix the time import, then create `.env.example`**

```python
# top of src/polymarket_mm_bot/bot.py, replace the placeholder time read:
import time
# ...
        now = time.time()
```

```bash
# .env.example
POLY_DRY_RUN=true
POLY_PRIVATE_KEY=
POLY_API_KEY=
POLY_API_SECRET=
POLY_API_PASSPHRASE=
POLY_FUNDER_ADDRESS=
POLY_CAPITAL_PER_WINDOW_USD=100
POLY_MAX_CONCURRENT_WINDOWS=1
POLY_N_LADDER_LEVELS=4
POLY_IMBALANCE_CEILING_SHARES=200
POLY_PULL_QUOTE_SECONDS=8
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-9, ~35 passed), confirms Task 10 didn't break any import.

- [ ] **Step 4: Manual dry-run smoke test against the live market**

```bash
cp .env.example .env   # POLY_DRY_RUN=true, no credentials needed for this
uv run python -m polymarket_mm_bot.bot --log-level INFO
```

Expected: log lines every ~2s showing a real `window=btc-updown-5m-<ts>`, a plausible
`midpoint_up` (something in roughly 0.05-0.95, tracking the live market), a nonzero
`levels` count, and `total_cost` near your configured `POLY_CAPITAL_PER_WINDOW_USD`. Let
it run across at least one window rollover (up to 5 minutes) and confirm the `window=`
value changes and quotes get pulled (`pulled quotes for ... ahead of resolution`) a few
seconds before each rollover. Stop with Ctrl-C. This is the "watch it for a few hours
before touching real funds" step from the design doc — the task here is just confirming
it runs cleanly end-to-end; leave it running longer on your own before ever flipping
`POLY_DRY_RUN=false`.

- [ ] **Step 5: Commit**

```bash
git add src/polymarket_mm_bot/bot.py .env.example
git commit -m "feat: wire bot main loop and add dry-run entry point"
git push
```

---

## Self-Review Notes

- **Spec coverage:** MarketTracker (design's MarketTracker), QuoteEngine (design's
  QuoteEngine, plus the reward-curve-shaped sizing decision from the backtest), OrderManager
  (design's OrderManager), InventoryTracker + skew (design's inventory imbalance handling),
  WindowCloser (design's pull-before-close + redemption placeholder — redemption itself is
  intentionally out of scope for this plan, see below), KillSwitch + dry-run (design's error
  handling / testing sections), Config (design's risk parameters, all tunable). All covered.
- **Known gap carried forward, not silently dropped (closed 2026-07-27):** the design doc's
  WindowCloser also "redeems settled positions after resolution" — this plan's
  `WindowCloser` only pulled quotes; redemption was deliberately deferred as a follow-up.
  It has since been built as a separate `RedemptionClient`/`DryRunRedeemer`
  (`src/polymarket_mm_bot/redemption.py`, Task 11, not tracked in this file's task list
  since it was added after this plan was executed) and wired into `bot.py`'s window-rollover
  handling. Building it surfaced a second, more important gap: `InventoryTracker.record_fill`
  was never called anywhere in the original Task 10 wiring, so `skew` and the redemption
  trigger both silently never fired in live mode — Task 10's dry-run smoke test couldn't
  catch this since dry-run mode legitimately has zero real fills. Fixed by adding
  `ClobClientProtocol.get_fills()` and `InventoryTracker.sync_from_fills()`, polled each
  loop iteration before computing skew.
- **Placeholder scan:** one intentional, explicitly-flagged placeholder exists in Task 10
  Step 1 (the time-read one-liner) and is fixed in Step 2 before the task is considered
  done — called out rather than silently left in, per the engineer running this plan should
  never be surprised by it.
- **Type consistency:** `Token = Literal["UP", "DOWN"]` defined once in `quote_engine.py`
  and imported everywhere else that needs it (`inventory.py`); `WindowInfo`, `LadderPlan`,
  `PlacedOrder`, `OrderIntent` each defined in exactly one module and imported, never
  redefined.
