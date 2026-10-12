# Shopee price tracker

A small Python Telegram bot for Shopee Singapore. Send a product link, choose an
exact variant, and receive an alert whenever its observed selling price falls.
Watches are saved until you untrack them.

**Live status:** automated tests cover the app and synthetic provider responses.
Real Shopee compatibility still needs verification after login: the earlier live
attempt redirected to **Login Required**, and no authenticated variant response
was captured. No real Telegram smoke test has been run without your bot token.
Run `price-check` successfully against your products before relying on alerts.

## Setup

Use Python **3.11+**, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and a Telegram account. These commands target macOS/Linux:

```sh
uv venv --python 3.11
source .venv/bin/activate
uv pip sync --require-hashes requirements-dev.lock
uv pip install --no-deps --no-build-isolation -e .
playwright install chromium
cp .env.example .env
```

Create a bot using `/newbot` with Telegram's **@BotFather**. Put its token in
`TELEGRAM_BOT_TOKEN` in `.env`. Set `TELEGRAM_USER_ID` to your numeric user ID;
you can find it in your Telegram account's data export or through a user-ID bot
you trust. Only that user in a private chat may operate this tracker.

```sh
shopee-tracker browser-setup
```

Sign in to Shopee in the dedicated browser. Open a product and check that you can
see its variant prices. Close the opened tab, or press Ctrl+C in the terminal,
when finished. The session is saved separately from your everyday browser profile.

With the bot stopped, test a **real product URL**:

```sh
shopee-tracker price-check 'https://shopee.sg/product/SHOP_ID/ITEM_ID'
```

Replace the example IDs with your product's IDs. Compare the reported variant,
price, and availability with Shopee. If the command reports `access`, sign in or
resolve Shopee's browser check manually. `unsupported` means the reader cannot
verify the current response shape and needs adapting; it never substitutes the
listing minimum for your chosen variant's price.

After that check succeeds:

```sh
shopee-tracker run
```

Open your bot's private chat and send `/start`, then paste a product link. You can
also use `python -m shopee_tracker` in place of `shopee-tracker`.

## Telegram commands

- Send a Singapore product URL or share link: select the variant with buttons.
  Single-option listings are tracked immediately. Repeated links do not duplicate
  an existing product/variant watch.
- `/list`: show watches, last valid prices, status, and last check time in SGT.
- `/untrack <id>` or **Untrack**: stop checks and discard queued alerts.
- `/help`: show the commands.

Singapore product URLs and redirects from `s.shopee.sg` and `shope.ee` are
supported. For app-only share links, copy the full product URL from your browser.

Prices are checked every 30 minutes while the app and computer are awake.
Each successful reading is compared with the preceding valid reading, including
increases. `S$100 → S$90 → S$95 → S$92` sends alerts at S$90 and S$92. The first
reading establishes a baseline. Unavailable options wait for a valid price.

Alerts include the variant, old/new price, savings, observation time, and link.
Only selling prices are tracked. Vouchers, coins, shipping, bundle conditions,
payment offers, and checkout totals are excluded. Future voucher evaluation can
consume price observations through the existing provider boundary.

## Configuration and recovery

| Variable | Meaning | Default |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather token | Required |
| `TELEGRAM_USER_ID` | Only permitted user | Required |
| `CHECK_INTERVAL_MINUTES` | Interval, 1–1440 minutes | `30` |
| `DATA_DIR` | Database and browser profile | `./data` |
| `BROWSER_HEADLESS` | Hide browser during checks | `false` |

Environment variables override `.env`. Run commands from the repository root,
or supply `DATA_DIR` and environment variables explicitly.

Stop the bot before browser setup or diagnostics; they share one profile.
`data/app.lock` prevents concurrent processes. After a crash, confirm all tracker
and setup processes have stopped before removing a stale lock file. Normal
shutdown removes it. Automatic stale-lock deletion is deliberately avoided.

`/list` statuses:

- `ok`: the latest read succeeded.
- `unavailable`: the selected variant is missing, sold out, or lacks a usable price.
- `access`: Shopee needs login or browser attention.
- `network`: the browser/network read failed.
- `unsupported`: the returned product data could not be verified.

Failures preserve the last valid price. Access incidents notify once per affected
watch until a successful reading resets the incident. After downtime, overdue
watches are checked once; price changes between checks cannot be recovered.

SQLite transactions save observations and their pending alerts together. Delivery
failures are retried with a shared cooldown that honors Telegram's `retry_after`.
Ambiguous delivery timeouts may produce duplicate messages. Untracking cancels
queued messages, but cannot retract a message already being sent.

Keep `.env` and `data/` private. Back up `data/tracker.sqlite` while the bot is
stopped. Treat the browser profile as a credential. The Python implementation
retains the earlier SQLite schema and pending-selection representation.

## Development

```sh
python scripts/check.py       # Ruff lint/format checks, strict mypy, unittest
python -m unittest discover -s tests -v
ruff format .
uv build --no-build-isolation # Build wheel and source distribution
```

Dependencies are pinned in `pyproject.toml` and the hash-checked requirements
locks. Development tools are included in `requirements-dev.lock`. There is no
Node/npm project tooling. The Playwright package manages its own browser driver.
The async API follows [Playwright's Python guidance](https://playwright.dev/python/docs/library).

The application separates the bot, HTTP client, browser provider, worker, and
SQLite store. Shutdown interrupts HTTP polling and drains browser work before
closing the database. Tests use real SQLite and controlled network boundaries.
Parser fixtures are **synthetic**, with provenance in `tests/fixtures/README.md`.

Live acceptance requires accessible single- and multi-variant listings, a saved
login, and a real bot conversation. See `docs/superpowers/` for the design and
verification record. No test suite result is presented as live price validation.

## Superpowers

Enable the **Superpowers** plugin in your coding agent, then open this repository.
`AGENTS.md` makes the relevant skills the default workflow. No plugin is silently
installed and no global agent configuration is changed.
