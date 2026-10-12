# Python Shopee tracker design

The user approved replacing the entire TypeScript implementation with Python and
replacing its initial Git commit with a fresh Python root commit. Work in place;
there are no user modifications or runtime files in the starting checkout.

Keep a single local process: asyncio Telegram long polling, sequential Playwright
browser reads, and SQLite transactions. Python 3.11+, httpx for HTTP, unittest
for deterministic tests, Ruff for lint/format, and mypy for type checks. Pin
runtime and development dependencies with hash-checked requirements lock files.
Use a src/shopee_tracker package and a `shopee-tracker` CLI with run,
browser-setup, and price-check commands. No Node/npm tooling remains.

Singapore/SGD only. Only the configured owner in a private Telegram chat may
operate the bot. Send a link, choose an exact variant, list or untrack watches.
Check daily at 12:00 noon Asia/Singapore while running. New watches receive an
immediate baseline; existing watches migrate to the noon schedule on startup.
Compare integer cents against the preceding valid reading, including increases;
first valid reading establishes the baseline.
Unavailable readings preserve the baseline. No vouchers, coins, shipping,
checkout discounts, website, or deployment in this version.

Persist watches, observations, pending selections, update cursor, notification
outbox, and delivery cooldown. Cancel queued alerts when untracking. Honor
Telegram retry_after across responses and notifications; ambiguous network
failures can duplicate messages. Recheck overdue watches once after downtime,
then resume at the next noon.
Failed price reads also resume at the next noon. Telegram delivery retries remain
independent of price-check scheduling.
A process lock protects the shared browser and database; stale lock files require
manual recovery after confirming other processes are stopped.

Keep provider, persistence, Telegram transport, and price rules separate. Reject
ambiguous identities, prices, currency, and unnamed multi-variant listings.
Retain the existing SQLite schema and pending selection wire representation so
an existing local data directory remains readable. Preserve Superpowers defaults.

Live access remains an unresolved acceptance gate: the previous real Shopee
attempt redirected to Login Required. Parser fixtures are synthetic and do not
prove current Shopee compatibility. No Telegram credentials have been provided.
The CLI must explain blocked access without inventing prices or leaking tokens.
