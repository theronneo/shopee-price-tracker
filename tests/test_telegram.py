import json
import unittest

import httpx

from shopee_tracker.telegram import TelegramClient, TelegramError


class TelegramTests(unittest.IsolatedAsyncioTestCase):
    async def test_payloads_are_plain_text_owner_only_with_poll_cursor(self):
        requests = []

        def transport(request):
            requests.append((str(request.url), json.loads(request.content)))
            return httpx.Response(200, json={"ok": True, "result": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = TelegramClient("123:secret", 42, http)
            await client.send(
                "<b>Untrusted name</b>", [[{"text": "Untrack", "callback_data": "u:1"}]]
            )
            await client.updates(19)
        self.assertEqual(requests[0][1]["chat_id"], 42)
        self.assertNotIn("parse_mode", requests[0][1])
        self.assertEqual(
            requests[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "u:1"
        )
        self.assertEqual(requests[1][1]["offset"], 19)
        self.assertEqual(requests[1][1]["allowed_updates"], ["message", "callback_query"])

    async def test_network_errors_do_not_disclose_token(self):
        def broken(request):
            raise httpx.ConnectError("https://api.telegram.org/bot123:secret", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as http:
            with self.assertRaises(TelegramError) as caught:
                await TelegramClient("123:secret", 42, http).send("test")
        self.assertNotIn("secret", str(caught.exception))

    async def test_server_cooldown_applies_to_following_requests(self):
        calls = []
        now = 100

        def limited(request):
            calls.append(request)
            return httpx.Response(
                429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 120}}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(limited)) as http:
            client = TelegramClient("123:secret", 42, http, clock=lambda: now)
            for _ in range(2):
                with self.assertRaises(TelegramError) as caught:
                    await client.send("test")
                self.assertEqual(caught.exception.retry_after, 120)
            self.assertEqual(len(calls), 1)
            now = 220
            with self.assertRaises(TelegramError):
                await client.send("test")
            self.assertEqual(len(calls), 2)

    async def test_existing_webhook_is_not_silently_deleted(self):
        calls = []

        def transport(request):
            calls.append(str(request.url))
            return httpx.Response(
                200, json={"ok": True, "result": {"url": "https://example.com/hook"}}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            with self.assertRaisesRegex(ValueError, "webhook"):
                await TelegramClient("123:secret", 42, http).verify()
        self.assertEqual(len(calls), 2)
