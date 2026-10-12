# Python Tracker Implementation Plan

> Use superpowers:executing-plans for inline implementation, meaningful test-first
> coverage, and one independent review. User explicitly authorized this rewrite.

**Goal:** Replace TypeScript with Python, retaining behavior, then create a fresh
root commit without the prior TypeScript commit in main's history.

**Architecture:** asyncio app, Playwright persistent profile, SQLite durable
watches/outbox, httpx Telegram client. Package src/shopee_tracker with one CLI.

**Spec:** ../specs/2026-10-12-tracker-design.md

## Global constraints

Python 3.11+, Singapore only, one owner/private chat, 30-minute default,
integer cents, exact variants, no fake live proof. Preserve runtime data.
Keep registry dependencies pinned and hash checked; no global configuration edits.

## Tasks

- [x] Core and configuration: port domain types, link validation, strict response
  parsing. Port existing unit cases first and add bool/NaN/foreign redirect cases.
  Interfaces: ProductRef, Variant, Product, async PriceProvider.product(ref).
- [x] Persistence: port Store with existing schema, observations/outbox transactions,
  selections, cooldown and cursors. Verify restart, stale checks, duplicates,
  missing initial price, failure recovery, and cancellation on untrack.
- [x] Bot and worker: port commands, pagination and variant choice. Test owner/group
  restrictions, update replay, fresh selection reads, retries and untrack races.
  Interfaces: Messenger.send/answer, Bot.handle(update), Tracker.tick().
- [x] Integrations and CLI: async httpx transport, serialized Playwright session,
  startup/shutdown, login and diagnostic commands. Test HTTP boundary payloads,
  token redaction, cooldown, session serialization, and setup errors.
- [x] Replace Node files, documentation and contributor guidance; pin dependencies.
  Run unittest, Ruff, mypy and package build. Independent read-only review and fixes.
- [ ] Replace main with a new Python root commit; remove obsolete remote tracking
  ref. Push to the fresh GitHub repository if it exists and transport permits.

## Review focus

Cancellation must finish workers before database close. Failed source reads must
not become zero prices. Rate limits affect the whole outbox. Huge or malformed
callback IDs must not crash SQLite calls. Live integration status stays explicit.

## Execution ledger

- User authorized history replacement; no force-push to an existing history needed.
- Working in place because the complete tracked project is being replaced.
- Prior source copied to a temporary reference directory; runtime data untouched.
- Python implementation and hash-checked dependency locks installed locally.
- Before the final review fix: 46 unittest cases passed; Ruff lint/format, strict
  mypy, and wheel/source builds passed. These use synthetic Shopee responses and
  controlled Telegram boundaries, not authenticated live services.
- Independent review found no critical or important issues. Its minor finding
  was Telegram rate-limit persistence for replies and polling. The transport now
  saves and restores the shared SQLite cooldown; startup waits for it and allows
  interruption during that wait.
- After that fix: Ruff lint/format, strict mypy (15 source files), distribution
  build, and `git diff --check` passed. The test suite was not rerun after the fix.
- History replacement is blocked by the workspace's read-only `.git` permission:
  `git checkout --orphan python-root` failed to create `.git/index.lock`.
  `main` and `origin/main` still reference `b1e129b`; no commit or push occurred.
- The GitHub repository URL returned 404. Recreate an empty repository before
  pushing the fresh local root commit. Live acceptance still needs the owner's
  Shopee login and Telegram token.
