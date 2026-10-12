import asyncio
import tempfile
import unittest
from pathlib import Path

from shopee_tracker.browser import BrowserSession, access_blocked
from shopee_tracker.lock import process_lock
from shopee_tracker.runtime import wait_or_stop


class LockTests(unittest.TestCase):
    def test_exclusive_lock_and_release(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with process_lock(directory):
                with self.assertRaisesRegex(ValueError, "Another"):
                    with process_lock(directory):
                        self.fail("Second owner acquired lock")
            with process_lock(directory):
                self.assertTrue((directory / "app.lock").exists())

    def test_stale_lock_is_not_deleted_during_acquisition(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            lock = directory / "app.lock"
            lock.write_text("2147483647")
            with self.assertRaisesRegex(ValueError, "lock"):
                with process_lock(directory):
                    pass
            self.assertEqual(lock.read_text(), "2147483647")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_cancels_long_poll_and_awaits_cleanup(self):
        stop = asyncio.Event()
        cleaned = asyncio.Event()
        started = asyncio.Event()

        async def work():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        task = asyncio.create_task(wait_or_stop(work(), stop))
        await asyncio.wait_for(started.wait(), 1)
        stop.set()
        self.assertIsNone(await task)
        self.assertTrue(cleaned.is_set())

    async def test_completed_long_poll_returns_value(self):
        async def work():
            return [1, 2]

        self.assertEqual(await wait_or_stop(work(), asyncio.Event()), [1, 2])

    async def test_session_serializes_pages_and_recovers_after_failed_reader(self):
        calls = []
        first_started = asyncio.Event()
        gate = asyncio.Event()

        class Page:
            async def close(self):
                calls.append("closed")

        class Context:
            async def new_page(self):
                calls.append("new")
                return Page()

            async def close(self):
                calls.append("context closed")

            def on(self, *args):
                pass

            def set_default_timeout(self, *args):
                pass

            def set_default_navigation_timeout(self, *args):
                pass

        async def launch(path, headless):
            return Context()

        session = BrowserSession(Path("/unused"), False, launch=launch)

        async def first():
            async with session.page():
                first_started.set()
                await gate.wait()
                raise ValueError("read failed")

        async def second():
            async with session.page():
                return 7

        one = asyncio.create_task(first())
        await first_started.wait()
        two = asyncio.create_task(second())
        await asyncio.sleep(0)
        self.assertEqual(calls, ["new"])
        gate.set()
        with self.assertRaisesRegex(ValueError, "read failed"):
            await one
        self.assertEqual(await two, 7)
        await session.close()
        self.assertEqual(calls, ["new", "closed", "new", "closed", "context closed"])

    def test_access_detection(self):
        self.assertTrue(access_blocked("https://shopee.sg/verify/traffic/error", ""))
        self.assertTrue(access_blocked("https://shopee.sg/buyer/login", ""))
        self.assertTrue(access_blocked("https://shopee.sg/product/1/2", "Login Required"))
        self.assertFalse(
            access_blocked("https://shopee.sg/product/1/2", "Security camera login guide")
        )
