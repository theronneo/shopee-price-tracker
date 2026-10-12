"""Small CLI for running the bot and maintaining its browser session."""

import argparse
import asyncio
import os
import signal
import sys

import httpx
from dotenv import load_dotenv
from playwright.async_api import Error as PlaywrightError

from .browser import BrowserSession
from .config import browser_config, load_config
from .domain import PriceError, money
from .links import resolve_product_url
from .lock import process_lock
from .runtime import run
from .shopee import ShopeeProvider
from .telegram import TelegramError


async def browser_setup() -> None:
    config = browser_config()
    with process_lock(config.data_dir):
        browser = BrowserSession(config.data_dir, False)
        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        installed = []
        for name in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(name, done.set)
                installed.append(name)
            except NotImplementedError:
                pass
        try:
            async with browser.page() as page:
                page.on("close", lambda _page: done.set())
                await page.goto("https://shopee.sg", wait_until="domcontentloaded")
                print(
                    "Sign in manually in this dedicated browser. Open a product and confirm its variant prices.\nClose the opened tab (or press Ctrl+C here) when finished; the session will be saved."
                )
                await done.wait()
        finally:
            try:
                await browser.close()
            finally:
                for name in installed:
                    loop.remove_signal_handler(name)


async def price_check(link: str) -> None:
    config = browser_config()
    with process_lock(config.data_dir):
        browser = BrowserSession(config.data_dir, config.headless)
        try:
            async with httpx.AsyncClient(follow_redirects=False) as http:
                product = await ShopeeProvider(browser).product(
                    await resolve_product_url(link, http)
                )
            print(product.name)
            print(product.ref.url)
            for variant in product.variants:
                price = money(variant.price_cents) if variant.price_cents is not None else "unknown"
                print(
                    f"{variant.id}\t{variant.name}\t{price}\t{'available' if variant.available else 'unavailable'}"
                )
            if not any(v.available for v in product.variants):
                raise PriceError("unavailable", "No purchasable variant price was verified.")
        finally:
            await browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Personal Shopee Singapore Telegram price tracker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="Run the Telegram bot and price checker")
    commands.add_parser(
        "browser-setup", help="Sign in manually using the dedicated browser profile"
    )
    check = commands.add_parser(
        "price-check", help="Inspect real variant prices without adding a watch or sending messages"
    )
    check.add_argument("url", help="Shopee Singapore product or share URL")
    args = parser.parse_args(argv)
    os.umask(0o077)
    load_dotenv(".env", override=False)
    try:
        if args.command == "run":
            asyncio.run(run(load_config()))
        elif args.command == "browser-setup":
            asyncio.run(browser_setup())
        else:
            asyncio.run(price_check(args.url))
    except PriceError as error:
        print(f"{error.reason}: {error}", file=sys.stderr)
        return 1
    except (ValueError, TelegramError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except PlaywrightError:
        print(
            "Browser setup failed. Run playwright install chromium, stop other tracker processes, and try again.",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPError:
        print("Network request failed. Check your connection and try again.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # Network exception tracebacks may contain a bot-token URL.
        print(
            f"Tracker stopped because of an unexpected {type(error).__name__}. Run the local checks before restarting.",
            file=sys.stderr,
        )
        return 1
    return 0
