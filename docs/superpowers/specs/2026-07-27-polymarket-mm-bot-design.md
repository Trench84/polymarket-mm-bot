# Polymarket BTC 5-min Market-Making Bot — Design

Date: 2026-07-27
Status: Draft — pending backtest/calibration phase before implementation

## Background

Analysis of an existing Polymarket wallet (`0x3048d65321be3497164cdfc2996f94f98a2e7537`,
handle `twitter-CryptoWithGab`) showed a bot trading exclusively the "BTC Up or Down 5m"
market series: 11,617 trades in ~7 weeks, +$140,913.78 all-time P/L, placing many small
laddered limit orders on both Up and Down within each 5-minute window and redeeming after
resolution. Its activity log shows explicit `Maker rebate` and `Taker rebate` entries,
indicating its edge is structural (fee/rebate capture), not directional prediction skill.

Polymarket runs two stacked incentive programs on eligible categories (Crypto included):

- **Maker Rebate Program**: taker fee = `0.07 * C * p * (1-p)` (C = shares, p = price).
  20% of collected taker fees fund a per-market rebate pool, split among makers pro-rata
  by each maker's `fee_equivalent` share of that market's filled maker volume. Payout
  requires actual fills; the reward curve peaks at p=0.5 and falls off toward the extremes.
- **Liquidity Rewards Program**: a separate, continuously-sampled quadratic score
  `S(v,s) = ((v-s)/v)^2 * b` for resting orders within a market-configured max spread `v`
  of the midpoint. Two-sided quoting is required to avoid a divide-by-`c` (c=3.0) penalty
  applied to single-sided liquidity. Sampled roughly every minute over a weekly epoch,
  size-weighted, paid from a separate per-market pool. The live BTC-5m order book confirmed
  an active rewards pool on this exact series.
- There is also a **tiered Taker Rebate Program** (volume-tiered rebate on taker fees paid)
  whose exact tiers are not published in help docs; needs runtime confirmation via the
  CLOB API's rewards/fees config endpoints.

Conclusion: the profitable strategy is continuous two-sided ladder market-making near the
live midpoint on each 5-minute window, not directional betting.

## Goal

Build a bot that replicates this pattern: quote a two-sided ladder on the BTC Up/Down 5-min
series, sized and positioned to earn both reward programs, while keeping net directional
exposure bounded and roughly balanced across each window.

## Non-goals

- No directional alpha / price prediction model for BTC.
- Single market series only (BTC Up/Down 5m) — not a general multi-asset or multi-interval
  framework.
- No custody, key management, or credential handling by any automated agent — the operator
  (user) owns and configures their own wallet/API keys; the bot reads them from local
  config/env at runtime.

## Stack

Python 3.11+, `py-clob-client` (official Polymarket CLOB SDK) for order signing/placement,
a websocket feed for live order book + market lifecycle events, `duckdb`/parquet for any
local historical data used in backtesting.

## Architecture

Single async-event-loop process, five components:

- **MarketTracker** — subscribes to the BTC Up/Down 5-min series; detects each new window
  (new token IDs) opening and the current window approaching resolution. Maps the logical
  series to the currently live market ID.
- **QuoteEngine** — strategy core. On each book update, computes the target ladder (price
  levels + sizes on both Up and Down) centered on the live midpoint, weighted toward the
  40-60c band (where both reward curves peak), tapering toward the market's max-spread
  cutoff, skewed opposite the current inventory imbalance.
- **OrderManager** — diffs the target ladder against currently-resting orders, cancels/
  replaces only what changed, enforces the fixed-$-per-window cap before submitting.
- **InventoryTracker** — tracks net Up/Down share exposure per window; feeds skew into
  QuoteEngine; triggers a hard quote-pull if imbalance exceeds a configured ceiling.
- **WindowCloser** — cancels all resting orders for a window ~5-10s before resolution
  (independent timer, not gated on book activity, so it can't be starved by a busy market);
  redeems settled positions after resolution.

## Risk parameters (config, all tunable)

- Fixed USD cap on capital at risk per individual 5-minute window.
- Global max concurrent-window exposure across all open windows.
- Hard inventory-imbalance ceiling (net Up-minus-Down shares) that forces a quote pull.
- Quote-pull timing before window close (default 5-10s).

## Inventory imbalance handling

Primary mechanism: skew quotes (widen/lower the overexposed side, tighten/raise the
deficient side) to passively nudge fills back toward balance — stays maker-only, keeps
earning rebates. If skewing doesn't resolve it before the imbalance ceiling, the bot pulls
quotes on the affected window rather than crossing the book (crossing as a taker was
considered and rejected for v1 — it pays taker fees and adds complexity for a
5-minute-lifetime position where riding out a bounded, capped imbalance to resolution is
cheaper than guaranteeing flatness).

## Error handling

All order placement/cancellation wrapped with retry-with-backoff for transient RPC/API
errors. A kill-switch (env var or file flag), checked every loop iteration, cancels all
open orders and halts new quoting. Any unhandled exception in the loop cancels that
window's orders before propagating — no silent failure that could leave naked resting
orders.

## Backtest / calibration phase (before going live)

Before risking capital, pull recent BTC-updown-5m trade history directly via Polymarket's
CLOB REST API (not via on-chain indexing — see "Prior art" below for why) and run a
calibration check modeled on the `prediction-market-analysis` repo's methodology:
Brier score / ECE / log-loss of realized outcome vs. traded price, bucketed by price.
Purpose: confirm there's no persistent pricing bias in this specific market that would
justify skewing the ladder asymmetrically, and sanity-check that maker-side excess returns
are non-negative before committing real funds (analogous to that repo's
`maker_vs_taker_returns` analysis, but computed on our own pulled sample since the
packaged dataset doesn't cover this market — see below).

## Prior art reviewed

[Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis)
is a research framework with pre-collected Polymarket/Kalshi trade datasets and an
analysis pipeline (DuckDB over Parquet), cited by several academic papers on prediction
market microstructure. Useful as a schema/methodology reference
(`docs/SCHEMAS.md`, `polymarket_win_rate_by_price.py`, `maker_vs_taker_returns.py`), but
its packaged dataset is **not usable as-is** for this project:

- Open issue [#35](https://github.com/Jon-Becker/prediction-market-analysis/issues/35):
  the indexer only decodes Polymarket's v1 CTF Exchange contracts; v2 (active since ~March
  2026) uses a different event ABI and is silently missing from the dataset. Our target
  market's entire relevant history (bot joined June 2026) falls in this gap.
- Open issue [#43](https://github.com/Jon-Becker/prediction-market-analysis/issues/43):
  unresolved question on whether the 5-min crypto series is indexed at trade-level
  granularity at all, plus a noted Gamma API pagination workaround needed to index it.
- Open issue [#33](https://github.com/Jon-Becker/prediction-market-analysis/issues/33):
  public Polygon RPCs are too slow for self-backfilling trades.

Decision: pull our own historical sample directly from the CLOB REST API for this single
market series rather than depending on or extending that repo's on-chain indexer.

## Testing

Dry-run mode as the default first step: compute and log intended orders/fills against the
live book without submitting, to observe behavior for a few hours before touching real
funds. Unit tests for QuoteEngine ladder math and InventoryTracker skew logic as pure
functions (no network).

## Open questions for next phase

- Exact tiered Taker Rebate thresholds (needs CLOB API rewards config lookup).
- Concrete ladder level count / spacing / size-taper function (to be tuned against
  backtest data, not guessed).
