# polymarket-mm-bot

Market-making bot for Polymarket's "BTC Up or Down 5m" series, aiming to capture the
platform's Maker Rebate and Liquidity Rewards programs via continuous two-sided quoting
rather than directional prediction.

Status: implemented and unit tested (81 tests), dry-run smoke tested against the live
market, including a live dashboard for monitoring and control. Not yet verified against a
real authenticated account — see [GOING_LIVE.md](GOING_LIVE.md) before running with
`POLY_DRY_RUN=false`.

See [docs/superpowers/specs/2026-07-27-polymarket-mm-bot-design.md](docs/superpowers/specs/2026-07-27-polymarket-mm-bot-design.md)
for the full design and
[docs/superpowers/plans/2026-07-27-polymarket-mm-bot-implementation.md](docs/superpowers/plans/2026-07-27-polymarket-mm-bot-implementation.md)
for the implementation plan.

Requires a Polymarket-linked Polygon wallet funded with USDC.e and CLOB API keys,
configured locally via env/config — this repo never stores or transmits credentials.

## Quick start

```bash
uv sync
uv run pytest          # 81 tests
```

### Dashboard (recommended)

A local web UI for entering credentials, tuning risk parameters, and starting/stopping/
monitoring the bot without touching the CLI:

```bash
uv run python -m polymarket_mm_bot.server
```

Open `http://127.0.0.1:8765` — binds to localhost only, never reachable over the network.
Fill in the Setup panel (or leave everything blank to just watch dry-run against the live
market with no credentials) and click **Start Bot**. Secrets are written to `.env` with
owner-only file permissions and are never echoed back to the browser after saving.

### CLI (no dashboard)

```bash
cp .env.example .env   # fill in your credentials before going live; dry-run needs none
uv run python -m polymarket_mm_bot.bot --log-level INFO   # dry-run by default
```
