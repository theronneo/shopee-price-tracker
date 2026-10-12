"""Normalize Shopee Singapore links and validate redirects before fetching."""

import re
from urllib.parse import SplitResult, urljoin, urlsplit

import httpx

from .domain import ProductRef

PRODUCT_HOSTS = {"shopee.sg", "www.shopee.sg"}
SHARE_HOSTS = {"s.shopee.sg", "shope.ee"}


def safe_shopee_url(value: str) -> SplitResult | None:
    try:
        url = urlsplit(value)
        if (
            url.scheme == "https"
            and url.hostname in PRODUCT_HOSTS | SHARE_HOSTS
            and not url.username
            and not url.password
            and url.port in {None, 443}
            and not any(char in value for char in "\\\r\n\t")
        ):
            return url
    except ValueError:
        pass
    return None


def parse_product_url(value: str) -> ProductRef | None:
    url = safe_shopee_url(value)
    if not url or url.hostname not in PRODUCT_HOSTS:
        return None
    match = re.fullmatch(r"/product/([1-9][0-9]*)/([1-9][0-9]*)/?", url.path)
    if not match:
        match = re.search(r"-i\.([1-9][0-9]*)\.([1-9][0-9]*)/?$", url.path)
    if not match:
        return None
    shop, item = match.groups()
    return ProductRef(shop, item, f"https://shopee.sg/product/{shop}/{item}")


async def resolve_product_url(value: str, client: httpx.AsyncClient) -> ProductRef:
    current = value
    for _ in range(6):
        url = safe_shopee_url(current)
        if not url:
            raise ValueError("Unsupported Shopee link. Send a Singapore product or share link.")
        ref = parse_product_url(current)
        if ref:
            return ref
        if url.hostname not in SHARE_HOSTS:
            raise ValueError("Unsupported Shopee link. Send a product URL.")
        async with client.stream("GET", current, follow_redirects=False, timeout=15) as response:
            location = response.headers.get("location")
            if not 300 <= response.status_code < 400 or not location:
                raise ValueError("Could not resolve the share link. Copy the full product URL.")
            current = urljoin(current, location)
    raise ValueError("Too many share-link redirects. Send the full product URL.")
