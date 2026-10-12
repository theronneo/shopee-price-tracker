"""Owner-only commands, persistent variant choices and watch management."""

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from .domain import PriceError, PriceProvider, Product, Variant, money
from .links import parse_product_url, resolve_product_url
from .store import Store
from .telegram import Keyboard, Messenger
from .tracker import singapore_time

PAGE_SIZE = 8
HELP = (
    "Send a Shopee Singapore product link to start tracking. Choose a variant when prompted.\n"
    "/list — watches and last check\n/untrack <id> — stop a watch\n/help — this message\n"
    "Checks run daily at 12:00 noon Singapore time while this app and your computer are awake. "
    "Missed checks run once when the app resumes. Alerts compare consecutive valid "
    "prices, excluding vouchers, coins and shipping."
)


class Bot:
    def __init__(
        self,
        store: Store,
        provider: PriceProvider,
        messenger: Messenger,
        owner: int,
        *,
        clock: Callable[[], float] = time.time,
        http: httpx.AsyncClient | None = None,
    ):
        self.store, self.provider, self.messenger = store, provider, messenger
        self.owner, self.clock, self.http = owner, clock, http

    async def handle(self, update: dict[str, Any]) -> None:
        update_id = update["update_id"]
        if update_id < self.store.offset():
            return
        callback = update.get("callback_query")
        message = (callback or {}).get("message") or update.get("message") or {}
        user = (callback or message).get("from") or {}
        chat = message.get("chat") or {}
        if (
            chat.get("type") == "private"
            and chat.get("id") == self.owner
            and user.get("id") == self.owner
        ):
            if callback:
                try:
                    await self.messenger.answer(callback["id"])
                except Exception:
                    pass  # An expired acknowledgement must not block the action.
                await self._callback(callback.get("data", ""))
            else:
                await self._message(message.get("text", ""), update_id)
        self.store.set_offset(update_id + 1)

    async def _message(self, text: str, update_id: int) -> None:
        pieces = text.split()
        command = pieces[0].split("@")[0] if pieces else ""
        if command in {"/start", "/help"}:
            await self.messenger.send(HELP)
            return
        if command == "/list":
            await self._list(0)
            return
        if command == "/untrack":
            if len(pieces) != 2 or not re.fullmatch(r"[0-9]{1,19}", pieces[1]):
                await self.messenger.send("Use /untrack <id>. Find the ID with /list.")
            else:
                await self._untrack(int(pieces[1]))
            return
        match = re.search(r"https://[^\s<>]+", text)
        if not match:
            await self.messenger.send(HELP)
            return
        link = match[0].rstrip("),.!?")
        try:
            ref = parse_product_url(link)
            if ref is None:
                if self.http is None:
                    raise ValueError("A share-link HTTP client is required.")
                ref = await resolve_product_url(link, self.http)
            product = await self.provider.product(ref)
        except (PriceError, ValueError, httpx.HTTPError) as error:
            await self._read_error(error)
            return
        if len(product.variants) == 1:
            await self._track(product, product.variants[0])
        else:
            token = self.store.save_selection(update_id, product, int(self.clock()))
            await self._choices(token, 0)

    async def _read_error(self, error: Exception) -> None:
        if isinstance(error, PriceError) and error.reason == "access":
            text = (
                "Shopee requires login or a browser check. Stop the bot, run "
                "shopee-tracker browser-setup, then restart and send the link again."
            )
        elif isinstance(error, PriceError):
            text = (
                "Could not verify this item’s exact variant prices. No watch was added. "
                "Try shopee-tracker price-check <link> locally after signing in."
            )
        else:
            text = (
                "Could not read that link. Send a full Shopee Singapore product URL "
                "and check your connection. No watch was added."
            )
        await self.messenger.send(text)

    async def _track(self, product: Product, variant: Variant) -> None:
        existing = self.store.find_watch(product.ref, variant.id)
        watch = self.store.add_watch(product, variant, int(self.clock()))
        price = (
            money(watch.last_price)
            if watch.last_price is not None
            else "Waiting for an available price"
        )
        await self.messenger.send(
            f"{'Already tracking' if existing else 'Tracking'} #{watch.id}\n{watch.name}\n"
            f"{watch.variant_name[:300]}\n{price}\nChecking daily at 12:00 noon Singapore time while running.\n{watch.ref.url}",
            [[{"text": "Untrack", "callback_data": f"u:{watch.id}"}]],
        )

    async def _choices(self, token: str, page: int) -> None:
        product = self.store.selection(token, int(self.clock()))
        if product is None or page < 0 or page * PAGE_SIZE >= len(product.variants):
            await self.messenger.send(
                "This selection is expired or invalid. Send the product link again."
            )
            return
        keyboard: Keyboard = [
            [
                {
                    "text": f"{variant.name[:48]} · {money(variant.price_cents) if variant.available and variant.price_cents is not None else 'unavailable'}",
                    "callback_data": f"s:{token}:{page * PAGE_SIZE + i}",
                }
            ]
            for i, variant in enumerate(product.variants[page * PAGE_SIZE : (page + 1) * PAGE_SIZE])
        ]
        nav = []
        if page:
            nav.append({"text": "Previous", "callback_data": f"p:{token}:{page - 1}"})
        if (page + 1) * PAGE_SIZE < len(product.variants):
            nav.append({"text": "Next", "callback_data": f"p:{token}:{page + 1}"})
        if nav:
            keyboard.append(nav)
        await self.messenger.send(
            f"{product.name}\nChoose the exact variant (page {page + 1}/{(len(product.variants) + PAGE_SIZE - 1) // PAGE_SIZE}). Prices are checked again when you choose.",
            keyboard,
        )

    async def _callback(self, data: str) -> None:
        if match := re.fullmatch(r"u:([0-9]{1,19})", data):
            await self._untrack(int(match[1]))
            return
        if match := re.fullmatch(r"l:([0-9]{1,19})", data):
            await self._list(int(match[1]))
            return
        if match := re.fullmatch(r"p:([0-9]{1,19}):([0-9]{1,19})", data):
            await self._choices(match[1], int(match[2]))
            return
        match = re.fullmatch(r"s:([0-9]{1,19}):([0-9]{1,19})", data)
        if not match:
            await self.messenger.send("This button is invalid. Send /help.")
            return
        token, index = match[1], int(match[2])
        selection = self.store.selection(token, int(self.clock()))
        if selection is None or index >= len(selection.variants):
            await self.messenger.send(
                "This selection is expired or invalid. Send the product link again."
            )
            return
        selected = selection.variants[index]
        try:
            product = await self.provider.product(selection.ref)
        except (PriceError, httpx.HTTPError) as error:
            await self._read_error(error)
            return
        variant = next((v for v in product.variants if v.id == selected.id), None)
        if variant is None:
            await self.messenger.send(
                "That variant is no longer listed. Send the link again to choose another."
            )
            return
        await self._track(product, variant)
        self.store.delete_selection(token)

    async def _untrack(self, watch_id: int) -> None:
        removed = self.store.untrack(watch_id)
        await self.messenger.send(
            f"Stopped tracking #{watch_id}."
            if removed
            else "That watch is already stopped or does not exist."
        )

    async def _list(self, page: int) -> None:
        watches = self.store.list_watches()
        if not watches:
            await self.messenger.send("No items tracked yet. Send a Shopee Singapore product link.")
            return
        page = min(max(page, 0), (len(watches) - 1) // PAGE_SIZE)
        rows = watches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        text = "\n\n".join(
            f"#{w.id} {w.name[:100]}\n{w.variant_name[:80]} · "
            f"{money(w.last_price) if w.last_price is not None else 'No valid price yet'}\n"
            f"Status: {w.status} · Last check: {singapore_time(w.last_checked)}"
            for w in rows
        )
        keyboard: Keyboard = [
            [{"text": f"Untrack #{w.id}", "callback_data": f"u:{w.id}"}] for w in rows
        ]
        nav = []
        if page:
            nav.append({"text": "Previous", "callback_data": f"l:{page - 1}"})
        if (page + 1) * PAGE_SIZE < len(watches):
            nav.append({"text": "Next", "callback_data": f"l:{page + 1}"})
        if nav:
            keyboard.append(nav)
        await self.messenger.send(text, keyboard)
