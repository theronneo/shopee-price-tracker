import unittest
from dataclasses import replace

from shopee_tracker.bot import Bot
from shopee_tracker.domain import PriceError, ProductRef
from shopee_tracker.store import Store
from shopee_tracker.telegram import TelegramError
from shopee_tracker.tracker import Tracker
from tests.helpers import PRODUCT, VARIANT, CaptureMessenger, StaticProvider


def message(text, update_id=1, user=42, chat_type="private"):
    return {
        "update_id": update_id,
        "message": {"from": {"id": user}, "chat": {"id": user, "type": chat_type}, "text": text},
    }


def callback(data, update_id=2):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "q",
            "from": {"id": 42},
            "message": {"chat": {"id": 42, "type": "private"}},
            "data": data,
        },
    }


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.sender = CaptureMessenger()
        self.provider = StaticProvider()
        self.bot = Bot(self.store, self.provider, self.sender, 42, 1800, clock=lambda: 100)

    async def test_unauthorized_and_group_messages_are_ignored(self):
        await self.bot.handle(message("/list", 1, 99))
        await self.bot.handle(message(PRODUCT.ref.url, 2, 42, "group"))
        self.assertEqual(self.sender.messages, [])
        self.assertEqual(self.store.list_watches(), [])

    async def test_selection_uses_fresh_price_and_deduplicates_watch(self):
        await self.bot.handle(message(PRODUCT.ref.url))
        self.assertEqual(self.store.list_watches(), [])
        choice = self.sender.messages[-1][1][0][0]["callback_data"]
        self.provider.value = replace(PRODUCT, variants=(replace(VARIANT, price_cents=9000),))
        await self.bot.handle(callback(choice))
        self.assertEqual(self.store.list_watches()[0].last_price, 9000)
        await self.bot.handle(message(PRODUCT.ref.url, 3))
        self.assertEqual(len(self.store.list_watches()), 1)
        self.assertIn("Already tracking", self.sender.messages[-1][0])
        await self.bot.handle(callback(self.sender.messages[-1][1][0][0]["callback_data"], 4))
        self.assertEqual(self.store.list_watches(), [])

    async def test_single_variant_and_replayed_update(self):
        self.provider.value = replace(PRODUCT, variants=(VARIANT,))
        update = message(PRODUCT.ref.url)
        await self.bot.handle(update)
        await self.bot.handle(update)
        self.assertEqual(len(self.store.list_watches()), 1)
        self.assertEqual(len(self.sender.messages), 1)

    async def test_expired_out_of_range_and_huge_callback_ids(self):
        await self.bot.handle(callback("s:999:0"))
        await self.bot.handle(message(PRODUCT.ref.url, 3))
        await self.bot.handle(callback("s:3:900", 4))
        await self.bot.handle(callback("u:9999999999999999999", 5))
        await self.bot.handle(message("/untrack " + "9" * 100, 6))
        self.assertEqual(self.store.list_watches(), [])

    async def test_variant_and_watch_pagination(self):
        self.provider.value = replace(
            PRODUCT,
            variants=tuple(replace(VARIANT, id=str(i), name=f"Option {i}") for i in range(12)),
        )
        await self.bot.handle(message(PRODUCT.ref.url))
        next_button = self.sender.messages[-1][1][-1][-1]["callback_data"]
        await self.bot.handle(callback(next_button))
        self.assertIn("Option 8", self.sender.messages[-1][1][0][0]["text"])
        for i in range(10):
            self.store.add_watch(PRODUCT, replace(VARIANT, id=str(i)), 1, 30)
        await self.bot.handle(message("/list", 3))
        await self.bot.handle(callback("l:1", 4))
        self.assertIn("#9 ", self.sender.messages[-1][0])
        self.assertNotIn("#1 ", self.sender.messages[-1][0])

    async def test_failed_confirmation_replays_without_duplicate_watch(self):
        self.provider.value = replace(PRODUCT, variants=(VARIANT,))

        class Offline(CaptureMessenger):
            async def send(self, text, keyboard=None):
                raise TelegramError(0)

        bot = Bot(self.store, self.provider, Offline(), 42, 1800, clock=lambda: 100)
        with self.assertRaises(TelegramError):
            await bot.handle(message(PRODUCT.ref.url))
        self.assertEqual(self.store.offset(), 0)
        await self.bot.handle(message(PRODUCT.ref.url))
        self.assertEqual(len(self.store.list_watches()), 1)
        self.assertEqual(self.store.offset(), 2)


class TrackerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.sender = CaptureMessenger()
        self.now = 100
        self.watch = self.store.add_watch(PRODUCT, VARIANT, 1, 30)

    async def test_drop_alert_and_retry(self):
        provider = StaticProvider(replace(PRODUCT, variants=(replace(VARIANT, price_cents=9000),)))

        class Flaky(CaptureMessenger):
            offline = True

            async def send(self, text, keyboard=None):
                if self.offline:
                    raise TelegramError(0)
                await super().send(text, keyboard)

        sender = Flaky()
        await Tracker(self.store, provider, sender, 30, clock=lambda: self.now).tick()
        self.assertEqual(self.store.get_watch(self.watch.id).last_price, 9000)
        sender.offline = False
        self.now = 161
        await Tracker(self.store, provider, sender, 30, clock=lambda: self.now).tick()
        self.assertEqual(len(sender.messages), 1)
        text = sender.messages[0][0]
        for part in ["S$100.00", "S$90.00", "S$10.00", PRODUCT.ref.url]:
            self.assertIn(part, text)

    async def test_untrack_during_read_suppresses_alert(self):
        store = self.store

        class RemovingProvider:
            async def product(self, ref):
                store.untrack(1)
                return replace(PRODUCT, variants=(replace(VARIANT, price_cents=100),))

        await Tracker(self.store, RemovingProvider(), self.sender, 30, clock=lambda: 100).tick()
        self.assertEqual(self.sender.messages, [])
        self.assertEqual(self.store.list_watches(), [])

    async def test_access_incident_is_not_spammed(self):
        class BlockedProvider:
            async def product(self, ref):
                raise PriceError("access", "Login required")

        tracker = Tracker(self.store, BlockedProvider(), self.sender, 30, clock=lambda: self.now)
        await tracker.tick()
        self.now = 200
        await tracker.tick()
        self.assertEqual(len(self.sender.messages), 1)
        self.assertEqual(self.store.get_watch(1).last_price, 10000)

    async def test_rate_limit_pauses_whole_outbox(self):
        second = self.store.add_watch(
            replace(PRODUCT, ref=ProductRef("1", "5", "https://shopee.sg/product/1/5")),
            VARIANT,
            1,
            30,
        )
        self.store.observe(1, 9000, 2, 30)
        self.store.observe(second.id, 9000, 2, 30)

        class Limited(CaptureMessenger):
            calls = 0

            async def send(self, text, keyboard=None):
                self.calls += 1
                raise TelegramError(429, 120)

        sender = Limited()
        for now in [100, 161]:
            await Tracker(
                self.store, StaticProvider(), sender, 30, clock=lambda now=now: now
            ).tick()
        self.assertEqual(sender.calls, 1)
        await Tracker(self.store, StaticProvider(), sender, 30, clock=lambda: 220).tick()
        self.assertEqual(sender.calls, 2)
