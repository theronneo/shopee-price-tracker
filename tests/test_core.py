import json
import unittest
from pathlib import Path

import httpx

from shopee_tracker.config import load_config
from shopee_tracker.domain import PriceError, ProductRef
from shopee_tracker.links import parse_product_url, resolve_product_url
from shopee_tracker.parser import parse_product

REF = ProductRef("123", "456", "https://shopee.sg/product/123/456")


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/product.json").read_text())


class LinksTests(unittest.IsolatedAsyncioTestCase):
    def test_canonical_product_formats(self):
        for url in [REF.url + "?x=1", "https://shopee.sg/Headphones-i.123.456?x=1"]:
            self.assertEqual(parse_product_url(url), REF)

    def test_unsafe_and_foreign_links(self):
        for url in [
            "https://shopee.com.my/product/1/2",
            "https://shopee.sg.evil.test/product/1/2",
            "https://x@shopee.sg/product/1/2",
            "http://shopee.sg/product/1/2",
            "https://shopee.sg:444/product/1/2",
            "https://shopee.sg/search",
            "https://shopee.sg/product/1/2/evil",
            "https://shopee.sg:bad/product/1/2",
        ]:
            with self.subTest(url=url):
                self.assertIsNone(parse_product_url(url))

    async def test_share_redirect_is_validated_before_following(self):
        requests = []

        def redirect(request):
            requests.append(str(request.url))
            return httpx.Response(302, headers={"location": REF.url})

        async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
            self.assertEqual(await resolve_product_url("https://s.shopee.sg/abc", client), REF)
        self.assertEqual(requests, ["https://s.shopee.sg/abc"])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
            )
        ) as client:
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                await resolve_product_url("https://s.shopee.sg/abc", client)

    async def test_redirect_loop_is_bounded(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(302, headers={"location": "/again"})
            )
        ) as client:
            with self.assertRaisesRegex(ValueError, "redirect"):
                await resolve_product_url("https://s.shopee.sg/abc", client)


class ParserTests(unittest.TestCase):
    def test_exact_variant_prices_and_stock(self):
        product = parse_product(fixture(), REF)
        self.assertEqual(
            [(v.id, v.price_cents, v.available) for v in product.variants],
            [("11", 1299, True), ("12", 1499, False)],
        )

    def test_identity_currency_and_absent_variants(self):
        for field, value in [("itemid", 789), ("currency", "MYR"), ("models", [])]:
            payload = fixture()
            payload["data"]["item"][field] = value
            with self.subTest(field=field), self.assertRaises(PriceError):
                parse_product(payload, REF)

    def test_missing_or_malformed_model_price_never_uses_listing_minimum(self):
        for value in [None, True, -1000, 1.5, 1299001, float("nan"), "1299000"]:
            payload = fixture()
            payload["data"]["item"]["models"][0]["price"] = value
            variant = parse_product(payload, REF).variants[0]
            self.assertIsNone(variant.price_cents)
            self.assertFalse(variant.available)

    def test_missing_or_boolean_stock_is_unavailable(self):
        for value in [None, True, float("nan")]:
            payload = fixture()
            payload["data"]["item"]["models"][0]["stock"] = value
            self.assertFalse(parse_product(payload, REF).variants[0].available)

    def test_unnamed_multi_variants_are_rejected(self):
        payload = fixture()
        for model in payload["data"]["item"]["models"]:
            model.pop("name")
        with self.assertRaisesRegex(PriceError, "label"):
            parse_product(payload, REF)
        payload["data"]["item"]["models"].pop()
        self.assertEqual(parse_product(payload, REF).variants[0].name, "Standard")

    def test_duplicate_variant_ids_are_rejected(self):
        payload = fixture()
        payload["data"]["item"]["models"][1]["modelid"] = 11
        with self.assertRaisesRegex(PriceError, "Duplicate"):
            parse_product(payload, REF)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_invalid_settings(self):
        env = {"TELEGRAM_BOT_TOKEN": "123:secret", "TELEGRAM_USER_ID": "42"}
        config = load_config(env)
        self.assertEqual(config.owner, 42)
        self.assertFalse(config.headless)
        for bad in [
            {"TELEGRAM_USER_ID": "0"},
            {"TELEGRAM_USER_ID": "1.5"},
            {"BROWSER_HEADLESS": "yes"},
            {"TELEGRAM_BOT_TOKEN": ""},
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                load_config(env | bad)
