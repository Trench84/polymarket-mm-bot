# Backtest / Calibration Results

Sample: 150 consecutive BTC Up/Down 5-min windows (~12.5 hours, one contiguous session
starting 2026-07-27), 320,647 trades, pulled directly from Polymarket's Gamma + data-api
REST endpoints (`backtest/pull_history.py`). Analysis in `backtest/calibration.py`.

## Headline numbers

| Metric | Value |
|---|---|
| Brier score (trade-level) | 0.1713 |
| Log loss | 0.5088 |
| ECE (trade-level) | 0.0242 |
| Windows won by Down / Up | 54.7% / 45.3% (n=150) |

The Brier score lands almost exactly on the ~0.17 benchmark the
`prediction-market-analysis` repo cites for a well-calibrated market with trades spread
across all price levels — i.e. **this market is priced efficiently overall**, not
obviously exploitable via a static directional bias.

The 54.7/45.3 Down/Up split is **not statistically significant** at n=150
(SE ≈ 4.1pp, so this is ~1.1 SE from 50/50) — one 12.5-hour session isn't enough to
distinguish a real skew from noise. Needs a much larger, multi-session sample before
treating it as real.

## Calibration by price (window-level, deduplicated by window x outcome x bucket)

Edge = realized win rate minus the price's implied probability, computed once per
(window, outcome, 5c-price-bucket) to avoid trade-count clustering (a single window can
contain hundreds of correlated trades, which would otherwise fake a much larger effective
sample size). Full table in `backtest/data/calibration_by_price.csv`.

- Most buckets show a small, fairly consistent **positive edge of +1pp to +5pp**
  (i.e. price slightly *under*-predicts the outcome that's already leading), most visible
  in the 45c-70c range, backed by ~150 independent windows per bucket.
- This is directionally consistent with known short-horizon crypto momentum (once BTC
  starts moving within the 5-min window, it tends to keep moving), but the effect is
  small and the sample is a single session — **not yet strong enough evidence to build an
  asymmetric/skewed ladder on**. Worth re-checking once a multi-day, multi-session sample
  is pulled.
- No evidence of a large, obviously exploitable mispricing anywhere in the curve.

## Volume concentration by price band

| Band | Share of $ volume |
|---|---|
| 40-60c (mid, reward-curve peak) | 23.3% |
| 60-80c | 19.8% |
| 80-95c | 17.5% |
| 20-40c | 8.3% |
| 5-20c | 2.1% |
| 0-5c + 95-100c (extremes) | 28.9% |

Almost 29% of raw dollar volume trades at the extremes (near-certain outcomes, mostly
late-window flow as the result becomes obvious). This matters because the Maker Rebate
formula (`fee_equivalent = C * feeRate * p * (1-p)`) makes that volume nearly worthless
for rebate purposes: `p*(1-p)` at p=0.99 is 0.0099 vs 0.25 at p=0.50 — a **25x** difference
per dollar traded. **Confirms the design's mid-band-weighted ladder is correct**: chasing
raw dollar volume near the edges would be a mistake, the reward math wants fills
concentrated in the 40-70c range regardless of how much total volume happens elsewhere.

## Conclusion

- No red flags: the market is efficiently priced, so the bot's edge should come from the
  rebate/rewards structure (as designed), not from a directional model.
- No green light yet for asymmetric skewing either — the momentum-shaped edge is
  suggestive but not yet statistically solid on one session's worth of data.
- Design's mid-band (40-70c) weighted ladder is empirically supported by where the
  reward-eligible volume actually concentrates.
- **Before going live**, worth pulling a larger sample (multiple days, spanning different
  times of day) with the same script and re-running this analysis, specifically to
  firm up or discard the momentum-edge signal and get a real read on the Up/Down base
  rate. Not a blocker for building the bot itself, since the core strategy doesn't depend
  on either being true.
