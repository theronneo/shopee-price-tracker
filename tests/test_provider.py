"""Exercise the adapter/parser boundary without authenticating to Shopee."""

import asyncio
import unittest

from shopee_tracker.domain import PriceError
from shopee_tracker.shopee import read_product_page
from tests.test_core import REF, fixture


class Response:
    url = "https://shopee.sg/api/v4/pdp/get_pc"
    status = 200
    ok = True

    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class Page:
    def __init__(self, response=None, url=REF.url, body="Product details"):
        self.response = response
        self.url = url
        self.body = body
        self.listener = None
        self.closed = False

    def on(self, event, listener):
        self.listener = listener

    def remove_listener(self, event, listener):
        self.listener = None

    async def route(self, pattern, callback):
        pass

    async def goto(self, url, **kwargs):
        if self.response:
            self.listener(self.response)
        await asyncio.sleep(0)

    def locator(self, selector):
        return self

    async def inner_text(self, **kwargs):
        return self.body

    async def close(self):
        self.closed = True


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_adapter_consumes_a_supported_response(self):
        page = Page(Response(fixture()))
        product = await read_product_page(page, REF, budget_seconds=0.1)
        self.assertEqual(product.variants[0].price_cents, 1299)
        self.assertTrue(page.closed)
        self.assertIsNone(page.listener)

    async def test_login_redirect_takes_precedence_over_product_data(self):
        page = Page(Response(fixture()), url="https://shopee.sg/verify/traffic/error")
        with self.assertRaises(PriceError) as caught:
            await read_product_page(page, REF, budget_seconds=0.1)
        self.assertEqual(caught.exception.reason, "access")
        self.assertTrue(page.closed)

    async def test_unrelated_response_cannot_supply_price(self):
        response = Response(fixture())
        response.url = "https://example.com/api/v4/pdp/get_pc"
        with self.assertRaises(PriceError) as caught:
            await read_product_page(Page(response), REF, budget_seconds=0.01)
        self.assertEqual(caught.exception.reason, "unsupported")

    async def test_matching_response_rate_limit_requires_browser_attention(self):
        response = Response({})
        response.status = 429
        response.ok = False
        with self.assertRaises(PriceError) as caught:
            await read_product_page(Page(response), REF, budget_seconds=0.1)
        self.assertEqual(caught.exception.reason, "access")
