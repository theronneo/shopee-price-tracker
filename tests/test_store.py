import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from shopee_tracker.schedule import next_noon
from shopee_tracker.store import Store
from tests.helpers import PRODUCT, VARIANT


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(lambda: self.store.close())

    def test_decreases_include_a_drop_after_an_increase(self):
        watch = self.store.add_watch(PRODUCT, VARIANT, 1)
        for time, price in [(2, 9000), (3, 9500), (4, 9200), (5, 9200)]:
            self.store.observe(watch.id, price, time)
        self.assertEqual(
            [(n.previous_cents, n.price_cents) for n in self.store.pending(10)],
            [(10000, 9000), (9500, 9200)],
        )
        self.assertEqual(self.store.get_watch(watch.id).last_price, 9200)

    def test_duplicate_watch_preserves_its_baseline(self):
        watch = self.store.add_watch(PRODUCT, VARIANT, 1)
        self.store.observe(watch.id, 9000, 2)
        again = self.store.add_watch(PRODUCT, VARIANT, 3)
        self.assertEqual(again.id, watch.id)
        self.assertEqual(again.last_price, 9000)

    def test_first_available_reading_does_not_alert(self):
        watch = self.store.add_watch(PRODUCT, replace(VARIANT, available=False), 1)
        self.assertIsNone(watch.last_price)
        self.store.observe(watch.id, 500, 2)
        self.assertEqual(self.store.pending(10), [])

    def test_failure_preserves_baseline_and_deduplicates_access_incident(self):
        watch = self.store.add_watch(PRODUCT, VARIANT, 1)
        self.store.fail_watch(watch.id, "access", 2)
        self.store.fail_watch(watch.id, "access", 3)
        self.assertEqual(len(self.store.pending(10)), 1)
        self.assertEqual(self.store.get_watch(watch.id).last_price, 10000)
        self.store.observe(watch.id, 9000, 4)
        self.assertEqual([n.kind for n in self.store.pending(10)], ["drop"])
        self.store.fail_watch(watch.id, "access", 5)
        self.assertEqual([n.kind for n in self.store.pending(10)], ["drop", "access"])

    def test_untrack_cancels_alerts_and_ignores_inflight_results(self):
        watch = self.store.add_watch(PRODUCT, VARIANT, 1)
        self.store.observe(watch.id, 9000, 2)
        self.assertTrue(self.store.untrack(watch.id))
        self.store.observe(watch.id, 8000, 3)
        self.assertEqual(self.store.pending(10), [])
        self.assertEqual(self.store.list_watches(), [])
        self.assertNotEqual(self.store.add_watch(PRODUCT, VARIANT, 4).id, watch.id)

    def test_invalid_prices_and_stale_results_do_not_overwrite_baseline(self):
        watch = self.store.add_watch(PRODUCT, VARIANT, 10)
        for price in [True, 0, -1, 1.5, float("nan"), 2**63]:
            with self.subTest(price=price), self.assertRaises(ValueError):
                self.store.observe(watch.id, price, 11)
        self.store.observe(watch.id, 500, 9)
        self.assertEqual(self.store.get_watch(watch.id).last_price, 10000)
        self.assertIsNone(self.store.get_watch(2**100))
        self.assertFalse(self.store.untrack(2**100))

    def test_selection_expiry(self):
        token = self.store.save_selection(1, PRODUCT, 100)
        self.assertEqual(self.store.selection(token, 101), PRODUCT)
        self.assertIsNone(self.store.selection(token, 86500))

    def test_restart_preserves_selections_alerts_cooldown_and_cursor(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tracker.sqlite"
            db = Store(path)
            watch = db.add_watch(PRODUCT, VARIANT, 1)
            token = db.save_selection(42, PRODUCT, 1)
            db.observe(watch.id, 9000, 2)
            notification = db.pending(10)[0]
            db.retry_notification(notification.id, 10, 60)
            db.defer_delivery(100)
            db.set_offset(43)
            db.close()
            db = Store(path)
            try:
                self.assertEqual(db.offset(), 43)
                self.assertEqual(db.selection(token, 20), PRODUCT)
                self.assertEqual(db.get_watch(watch.id).last_price, 9000)
                self.assertEqual(db.pending(99), [])
                self.assertEqual(len(db.pending(100)), 1)
                self.assertEqual(db.due(next_noon(2) - 1), [])
                self.assertEqual(len(db.due(next_noon(2))), 1)
                db.mark_sent(notification.id)
                self.assertEqual(db.pending(101), [])
            finally:
                db.close()

    def test_future_database_version_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "future.sqlite"
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA user_version=99")
            conn.close()
            with self.assertRaisesRegex(ValueError, "version"):
                Store(path)
