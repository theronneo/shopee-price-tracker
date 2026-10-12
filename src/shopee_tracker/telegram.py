"""Telegram HTTP transport with shared cooldown and redacted failures."""

import math
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

Keyboard = list[list[dict[str, str]]]


class Messenger(Protocol):
    async def send(self, text: str, keyboard: Keyboard | None = None) -> None: ...
    async def answer(self, query_id: str) -> None: ...


class CooldownStore(Protocol):
    def delivery_resume(self) -> int: ...
    def defer_delivery(self, until: int) -> None: ...


class TelegramError(Exception):
    def __init__(self, code: int, retry_after: int = 5):
        super().__init__(f"Telegram request failed ({code}).")
        self.code = code
        self.retry_after = retry_after


class TelegramClient:
    def __init__(
        self,
        token: str,
        owner: int,
        http: httpx.AsyncClient,
        clock: Callable[[], float] = time.time,
        cooldown: CooldownStore | None = None,
    ):
        self._token = token
        self.owner = owner
        self.http = http
        self.clock = clock
        self.cooldown = cooldown
        self.blocked_until = 0.0

    async def _call(self, method: str, body: dict[str, Any]) -> Any:
        if self.cooldown is not None:
            self.blocked_until = max(self.blocked_until, self.cooldown.delivery_resume())
        now = self.clock()
        if now < self.blocked_until:
            raise TelegramError(429, math.ceil(self.blocked_until - now))
        try:
            response = await self.http.post(
                f"https://api.telegram.org/bot{self._token}/{method}", json=body, timeout=40
            )
            result = response.json()
        except (httpx.HTTPError, ValueError):
            raise TelegramError(0) from None
        if not isinstance(result, dict):
            raise TelegramError(response.status_code)
        if not result.get("ok"):
            code = result.get("error_code", response.status_code)
            params = result.get("parameters") or {}
            retry = params.get("retry_after", 5) if isinstance(params, dict) else 5
            retry = max(1, retry) if type(retry) is int else 5
            if code == 429:
                self.blocked_until = math.ceil(self.clock() + retry)
                if self.cooldown is not None:
                    self.cooldown.defer_delivery(int(self.blocked_until))
            raise TelegramError(code if type(code) is int else response.status_code, retry)
        return result.get("result")

    async def send(self, text: str, keyboard: Keyboard | None = None) -> None:
        body: dict[str, Any] = {
            "chat_id": self.owner,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if keyboard:
            body["reply_markup"] = {"inline_keyboard": keyboard}
        await self._call("sendMessage", body)

    async def answer(self, query_id: str) -> None:
        await self._call("answerCallbackQuery", {"callback_query_id": query_id})

    async def updates(self, offset: int) -> list[dict[str, Any]]:
        result = await self._call(
            "getUpdates",
            {"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]},
        )
        if not isinstance(result, list) or any(
            not isinstance(row, dict) or type(row.get("update_id")) is not int for row in result
        ):
            raise TelegramError(0)
        return result

    async def verify(self) -> None:
        await self._call("getMe", {})
        webhook = await self._call("getWebhookInfo", {})
        if isinstance(webhook, dict) and webhook.get("url"):
            raise ValueError(
                "This bot already has a webhook. Use a dedicated bot or remove its webhook before local polling."
            )
