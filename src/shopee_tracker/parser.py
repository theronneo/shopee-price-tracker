"""Strict item/model parser; unsupported payloads never become observations."""

import math
from typing import Any

from .domain import PriceError, Product, ProductRef, Variant


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _identity(value: Any) -> str | None:
    if type(value) is int and 0 <= value <= 2**53 - 1:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return value
    return None


def _cents(value: Any) -> int | None:
    # Shopee's supported item/model shape uses 100,000 units per SGD.
    # Booleans, fractional cents and unfamiliar representations fail closed.
    if type(value) is int and 0 < value <= 2**53 - 1 and value % 1000 == 0:
        return value // 1000
    return None


def parse_product(payload: object, ref: ProductRef) -> Product:
    root = _object(payload)
    if root.get("error"):
        raise PriceError("unsupported", "Shopee returned an error instead of item data.")
    data = _object(root.get("data"))
    item = _object(data.get("item") or root.get("item") or root.get("data"))
    if _identity(item.get("shopid")) != ref.shop_id or _identity(item.get("itemid")) != ref.item_id:
        raise PriceError("unsupported", "Product identity could not be verified.")
    if item.get("currency") != "SGD":
        raise PriceError("unsupported", "Product currency is not SGD.")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PriceError("unsupported", "Product title is missing.")
    models = item.get("models")
    if not isinstance(models, list) or not models:
        raise PriceError("unsupported", "Explicit variant data is missing.")
    variants = []
    for raw in models:
        model = _object(raw)
        label = model.get("name")
        if len(models) > 1 and (not isinstance(label, str) or not label.strip()):
            raise PriceError("unsupported", "A variant label is missing.")
        model_id = _identity(model.get("modelid"))
        if model_id is None:
            raise PriceError("unsupported", "A variant identity is missing.")
        price = _cents(model.get("price"))
        stock = model.get("stock")
        if stock is None:
            stock = _object(_object(model.get("stock_info_v2")).get("summary_info")).get(
                "total_available_stock"
            )
        available = (
            isinstance(stock, (int, float))
            and not isinstance(stock, bool)
            and 0 < stock <= 2**53 - 1
            and math.isfinite(stock)
            and stock > 0
            and price is not None
        )
        variants.append(
            Variant(
                model_id,
                label if isinstance(label, str) and label.strip() else "Standard",
                price,
                available,
            )
        )
    if len({v.id for v in variants}) != len(variants):
        raise PriceError("unsupported", "Duplicate variant identities.")
    return Product(ref, name[:300], tuple(variants))
