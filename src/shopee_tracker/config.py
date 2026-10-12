"""Validate configuration before opening the browser or database."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserConfig:
    data_dir: Path
    headless: bool


@dataclass(frozen=True)
class Config(BrowserConfig):
    token: str
    owner: int


def browser_config(env: Mapping[str, str] | None = None) -> BrowserConfig:
    values = os.environ if env is None else env
    headless = values.get("BROWSER_HEADLESS", "false")
    if headless not in {"true", "false"}:
        raise ValueError("BROWSER_HEADLESS must be true or false.")
    return BrowserConfig(
        Path(values.get("DATA_DIR") or "./data").expanduser().resolve(), headless == "true"
    )


def load_config(env: Mapping[str, str] | None = None) -> Config:
    values = os.environ if env is None else env
    browser = browser_config(values)
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("Set TELEGRAM_BOT_TOKEN in .env using the token from @BotFather.")
    try:
        owner = int(values.get("TELEGRAM_USER_ID", ""))
        if not 0 < owner < 2**63:
            raise ValueError
    except ValueError:
        raise ValueError(
            "Set TELEGRAM_USER_ID to your positive numeric Telegram user ID."
        ) from None
    return Config(browser.data_dir, browser.headless, token, owner)
