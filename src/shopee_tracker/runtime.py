"""Cooperative shutdown: drain browser work before closing its database."""

import asyncio
import signal
from collections.abc import Awaitable
from typing import TypeVar

import httpx

from .bot import Bot
from .browser import BrowserSession
from .config import Config
from .lock import process_lock
from .shopee import ShopeeProvider
from .store import Store
from .telegram import TelegramClient, TelegramError
from .tracker import Tracker

T = TypeVar("T")


async def wait_or_stop(awaitable: Awaitable[T], stop: asyncio.Event) -> T | None:
    """Interrupt HTTP polling or a timer; never use this to cancel Playwright calls."""
    work = asyncio.ensure_future(awaitable)
    stopped = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({work, stopped}, return_when=asyncio.FIRST_COMPLETED)
        return work.result() if work in done else None
    finally:
        for task in (work, stopped):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, stopped, return_exceptions=True)


async def _poll(bot: Bot, telegram: TelegramClient, store: Store, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            updates = await wait_or_stop(telegram.updates(store.offset()), stop)
            for update in updates or []:
                if stop.is_set():
                    break
                await bot.handle(update)
        except TelegramError as error:
            if error.code in {401, 409}:
                raise ValueError(
                    "Telegram rejected polling. Check the token and ensure only one bot process runs."
                ) from None
            print("Telegram polling failed; retrying.")
            await wait_or_stop(asyncio.sleep(max(5, error.retry_after)), stop)


async def _check(tracker: Tracker, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await tracker.tick(stop)
        await wait_or_stop(asyncio.sleep(5), stop)


async def _guard(work: Awaitable[None], stop: asyncio.Event) -> None:
    try:
        await work
    except BaseException:
        stop.set()
        raise


async def _verify(telegram: TelegramClient, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await wait_or_stop(telegram.verify(), stop)
            return
        except TelegramError as error:
            if error.code != 429:
                raise
            await wait_or_stop(asyncio.sleep(error.retry_after), stop)


async def run(config: Config) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = []
    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(name, stop.set)
            signals.append(name)
        except NotImplementedError:
            pass
    try:
        with process_lock(config.data_dir):
            store = Store(config.data_dir / "tracker.sqlite")
            browser = BrowserSession(config.data_dir, config.headless)
            try:
                async with httpx.AsyncClient(follow_redirects=False) as http:
                    telegram = TelegramClient(config.token, config.owner, http, cooldown=store)
                    await _verify(telegram, stop)
                    if stop.is_set():
                        return
                    provider = ShopeeProvider(browser)
                    bot = Bot(store, provider, telegram, config.owner, config.interval, http=http)
                    tracker = Tracker(store, provider, telegram, config.interval)
                    print(
                        f"Tracker running. Checking every {config.interval / 60:g} minutes. Send your bot /start. Ctrl+C stops it."
                    )
                    results = await asyncio.gather(
                        _guard(_poll(bot, telegram, store, stop), stop),
                        _guard(_check(tracker, stop), stop),
                        return_exceptions=True,
                    )
                    for result in results:
                        if isinstance(result, BaseException):
                            raise result
            finally:
                stop.set()
                try:
                    await browser.close()
                finally:
                    store.close()
    finally:
        for name in signals:
            loop.remove_signal_handler(name)
