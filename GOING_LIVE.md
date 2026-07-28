# Going Live Checklist

The bot has been built, unit tested (81 tests), and dry-run smoke tested against the
live market. What it has **not** been tested against is your real account — I have no
credentials, so `LiveClobClient` and `RedemptionClient`'s parsing of real API responses
is verified against Polymarket's documented shapes, not an actual authenticated call.
This checklist exists to close that gap deliberately, in small/cheap/reversible steps,
before any meaningful capital is on the line.

Steps below show the CLI (`uv run python -m polymarket_mm_bot.bot`), but everything
also works from the dashboard (`uv run python -m polymarket_mm_bot.server`, then
`http://127.0.0.1:8765`) — Start/Stop replace the CLI/`.stop` flag, and the Setup panel
replaces editing `.env` by hand. The dashboard binds to localhost only, but it does hold
your credentials in `.env` on this machine once saved — same trust boundary as the CLI,
just with a form instead of a text editor. Don't expose port 8765 to anything but this
machine (no port-forwarding, no tunneling it to another device).

Work through it in order. Don't skip ahead because a step "should" work.

## 0. Prerequisites

- [ ] `.env` filled in from `.env.example` — wallet private key, CLOB API key/secret/
      passphrase, funder address.
- [ ] `POLY_POLYGON_RPC_URL` pointed at a real provider (Alchemy/Infura/QuickNode), not
      the public default — redemption needs a reliable RPC to submit transactions.
- [ ] `POLY_CAPITAL_PER_WINDOW_USD` and `POLY_IMBALANCE_CEILING_SHARES` set low for this
      first run. You're not testing the strategy yet, you're testing the code.
- [ ] `POLY_DRY_RUN` still `true` for step 1.

## 1. Confirm dry-run is still healthy

```bash
uv run python -m polymarket_mm_bot.bot --log-level INFO
```
Watch for at least one window rollover (up to 5 min). Expect: a real `midpoint_up`
tracking the live market, a `pulled quotes` line a few seconds before each window ends,
and the `window=` slug changing on rollover. `touch .stop` to stop it, confirm it logs
`kill switch triggered` and exits.

## 2. First real order — placement and cancellation only

Set `POLY_DRY_RUN=false`, run the bot, and as soon as it logs its first order placement:

- [ ] Open Polymarket's own UI (or `client.get_open_orders()` via a quick script) and
      confirm the order actually appears, at the price/size the bot logged.
- [ ] Let `OrderManager` cancel/replace it on the next poll (or `touch .stop` to force a
      `cancel_all`) and confirm it disappears from Polymarket's UI too.

If `PlacedOrder.order_id`/`price`/`size` look wrong in the logs compared to what
Polymarket shows, the field names in `LiveClobClient.place_order`/`get_open_orders`
(`src/polymarket_mm_bot/clob_client.py`) need adjusting to match your account's actual
response shape.

## 3. One real fill — inventory tracking

Let a resting order actually get filled (small size makes this more likely quickly).

- [ ] Confirm the next log line's `skew` value moves off `0.00` — that means
      `get_fills()` → `InventoryTracker.sync_from_fills()` picked up the real fill.
- [ ] Cross-check the share count against what Polymarket's UI shows you're holding.

If `skew` stays `0.00` after a fill you can see on Polymarket's UI, `LiveClobClient.
get_fills()`'s field mapping (`asset_id`, `size`) needs adjusting.

## 4. One resolved window — redemption

Let a window you held a position in resolve.

- [ ] Watch for a `redeemed <slug> -> <tx_hash>` log line within the next rollover.
- [ ] Look up that tx hash on Polygonscan, confirm it's a successful `redeemPositions`
      call to `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`.
- [ ] Confirm your wallet's USDC.e balance actually increased.

If it logs a failure instead, that's expected to happen occasionally (see retry queue
below) — but if it *never* succeeds across several windows, check `.redemption_queue.json`
for the accumulating attempt count and investigate before assuming it'll sort itself out.

## 5. Kill switch, for real

- [ ] With live orders resting, `touch .stop` and confirm every order actually
      disappears from Polymarket's UI, not just the logs.

## 6. Only after all five pass

Increase `POLY_CAPITAL_PER_WINDOW_USD` and `POLY_IMBALANCE_CEILING_SHARES` gradually,
watching each change for at least a few windows before increasing again.

---

**Before any of this:** use a wallet funded only with what you're willing to lose to
this bot, not your main one. This is ~56 unit tests and one afternoon of dry-run/live
smoke testing, not a security audit.
