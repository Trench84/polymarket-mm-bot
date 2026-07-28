# polymarket-mm-bot

Market-making bot for Polymarket's "BTC Up or Down 5m" series, aiming to capture the
platform's Maker Rebate and Liquidity Rewards programs via continuous two-sided quoting
rather than directional prediction.

Design status: draft, pending a backtest/calibration phase before implementation.
See [docs/superpowers/specs/2026-07-27-polymarket-mm-bot-design.md](docs/superpowers/specs/2026-07-27-polymarket-mm-bot-design.md)
for the full design.

Requires a Polymarket-linked Polygon wallet funded with USDC.e and CLOB API keys,
configured locally via env/config — this repo never stores or transmits credentials.
