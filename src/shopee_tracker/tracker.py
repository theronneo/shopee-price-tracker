"""Sequential checking and durable, rate-limited notification delivery."""

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .domain import PriceError, PriceProvider, money
from .store import Notification, Store
from .telegram import Messenger, TelegramError


def singapore_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Singapore")).strftime(
        "%d %b %Y %H:%M SGT"
    )


def alert_text(event: Notification) -> str:
    header = f"{event.name}\n{event.variant_name[:300]}"
    if event.kind == "access":
        return (
            f"{header}\nShopee needs your attention. Stop the bot, run "
            f"shopee-tracker browser-setup, then restart it. Your last valid price is saved.\n{event.url}"
        )
    previous, current = event.previous_cents, event.price_cents
    assert previous is not None and current is not None
    return (
        f"Price dropped!\n{header}\n{money(previous)} → {money(current)}\n"
        f"Save {money(previous - current)} ({(previous - current) / previous * 100:.1f}%)\n"
        f"Observed {singapore_time(event.created_at)}\n{event.url}"
    )


class Tracker:
    def __init__(
        self,
        store: Store,
        provider: PriceProvider,
        messenger: Messenger,
        interval: int,
        clock: Callable[[], float] = time.time,
    ):
        self.store, self.provider, self.messenger = store, provider, messenger
        self.interval, self.clock = interval, clock
        self._busy = False

    async def tick(self, stop: asyncio.Event | None = None) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            await self._deliver(stop)
            for watch in self.store.due(int(self.clock())):
                if stop and stop.is_set():
                    break
                if not self.store.get_watch(watch.id):
                    continue
                try:
                    product = await self.provider.product(watch.ref)
                    variant = next((v for v in product.variants if v.id == watch.variant_id), None)
                    if not variant or not variant.available or variant.price_cents is None:
                        raise PriceError("unavailable", "Selected variant unavailable.")
                except PriceError as error:
                    self.store.fail_watch(watch.id, error.reason, int(self.clock()), self.interval)
                except (OSError, httpx.HTTPError):
                    self.store.fail_watch(watch.id, "network", int(self.clock()), self.interval)
                else:
                    # Storage failures propagate: they are not failed source reads.
                    self.store.observe(
                        watch.id, variant.price_cents, int(self.clock()), self.interval
                    )
                await self._deliver(stop)
        finally:
            self._busy = False

    async def _deliver(self, stop: asyncio.Event | None) -> None:
        for event in self.store.pending(int(self.clock())):
            if stop and stop.is_set():
                break
            if not self.store.get_watch(event.watch_id):
                continue
            try:
                await self.messenger.send(
                    alert_text(event),
                    [[{"text": "Untrack", "callback_data": f"u:{event.watch_id}"}]],
                )
            except TelegramError as error:
                retry = max(min(3600, 60 * 2 ** min(event.attempts, 6)), error.retry_after)
                now = int(self.clock())
                self.store.retry_notification(event.id, now, retry)
                self.store.defer_delivery(now + retry)
                break
            else:
                self.store.mark_sent(event.id)
