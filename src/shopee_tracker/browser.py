"""A dedicated persistent browser profile, with one reader at a time."""

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

Launcher = Callable[[Path, bool], Awaitable[BrowserContext]]


def access_blocked(url: str, text: str) -> bool:
    return bool(
        re.match(r"^/(verify|buyer/login|login)(/|$)", urlsplit(url).path)
        or re.search(
            r"Login Required|verify you are human|unusual traffic|security verification", text, re.I
        )
    )


class BrowserSession:
    def __init__(self, data_dir: Path, headless: bool = False, *, launch: Launcher | None = None):
        self.profile = data_dir / "browser-profile"
        self.headless = headless
        self._launch = launch or self._launch_context
        self._lock = asyncio.Lock()
        self._context: BrowserContext | None = None
        self._playwright: Playwright | None = None
        self._closed = False

    async def _launch_context(self, path: Path, headless: bool) -> BrowserContext:
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True, mode=0o700)
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return await self._playwright.chromium.launch_persistent_context(
            str(path),
            headless=headless,
            locale="en-SG",
            timezone_id="Asia/Singapore",
            viewport={"width": 1280, "height": 900},
        )

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        async with self._lock:
            if self._closed:
                raise ValueError("Browser session is closed.")
            if self._context is None:
                context = await self._launch(self.profile, self.headless)
                context.set_default_timeout(15000)
                context.set_default_navigation_timeout(30000)

                def clear(_context: BrowserContext) -> None:
                    if self._context is context:
                        self._context = None

                context.on("close", clear)
                self._context = context
            page = await self._context.new_page()
            try:
                yield page
            finally:
                await page.close()

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            try:
                if self._context is not None:
                    await self._context.close()
                    self._context = None
            finally:
                if self._playwright is not None:
                    await self._playwright.stop()
                    self._playwright = None
