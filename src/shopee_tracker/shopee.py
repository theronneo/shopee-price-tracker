"""Read supported item responses emitted by the real product page."""

import asyncio
import re
import time
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response, Route

from .browser import access_blocked
from .domain import PriceError, Product, ProductRef
from .links import parse_product_url, safe_shopee_url
from .parser import parse_product


class PageSession(Protocol):
    def page(self) -> AbstractAsyncContextManager[Page]: ...


class ShopeeProvider:
    def __init__(self, browser: PageSession):
        self.browser = browser

    async def product(self, ref: ProductRef) -> Product:
        canonical = parse_product_url(ref.url)
        if canonical != ref:
            raise PriceError("unsupported", "Invalid product identity.")
        try:
            async with self.browser.page() as page:
                return await read_product_page(page, ref)
        except (PlaywrightError, OSError):
            raise PriceError(
                "network", "Browser read failed. Check browser installation and connectivity."
            ) from None


async def read_product_page(page: Page, ref: ProductRef, *, budget_seconds: float = 15) -> Product:
    product: Product | None = None
    last_error: PriceError | None = None
    pending: set[asyncio.Task[None]] = set()

    async def consume(response: Response) -> None:
        nonlocal product, last_error
        try:
            product = parse_product(await response.json(), ref)
        except PriceError as error:
            last_error = error
        except (PlaywrightError, ValueError):
            last_error = PriceError("unsupported", "Unreadable Shopee response.")

    def receive(response: Response) -> None:
        nonlocal last_error
        url = urlsplit(response.url)
        if url.hostname != "shopee.sg" or not re.fullmatch(
            r"/api/v4/(pdp/get_pc|pdp/get|item/get)", url.path
        ):
            return
        if response.status in {401, 403, 429}:
            last_error = PriceError("access", "Shopee requires browser attention.")
        elif response.ok:
            task = asyncio.create_task(consume(response))
            pending.add(task)
            task.add_done_callback(pending.discard)

    async def route_request(route: Route) -> None:
        request = route.request
        if (
            request.is_navigation_request()
            and request.frame == page.main_frame
            and not safe_shopee_url(request.url)
        ):
            await route.abort()
        else:
            await route.continue_()

    page.on("response", receive)
    await page.route("**/*", route_request)
    try:
        await page.goto(ref.url, wait_until="domcontentloaded")
        deadline = time.monotonic() + budget_seconds
        while time.monotonic() < deadline:
            try:
                text = await page.locator("body").inner_text(timeout=2000)
            except PlaywrightError:
                text = ""
            if access_blocked(page.url, text):
                raise PriceError("access", "Shopee requires login or verification.")
            if product is not None:
                return product
            if last_error is not None and last_error.reason == "access":
                raise last_error
            await asyncio.sleep(0.1)
        raise last_error or PriceError(
            "unsupported",
            "No supported variant response was observed. Run price-check after signing in.",
        )
    finally:
        page.remove_listener("response", receive)
        await page.close()
        await asyncio.gather(*pending, return_exceptions=True)
