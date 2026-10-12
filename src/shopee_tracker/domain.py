"""Values shared by the provider, persistence and Telegram layers."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Reason = Literal["access", "unavailable", "network", "unsupported"]


@dataclass(frozen=True)
class ProductRef:
    shop_id: str
    item_id: str
    url: str


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    price_cents: int | None
    available: bool


@dataclass(frozen=True)
class Product:
    ref: ProductRef
    name: str
    variants: tuple[Variant, ...]
    currency: str = "SGD"

    def to_dict(self) -> dict[str, Any]:
        # Keep pending selections compatible with the original SQLite schema.
        return {
            "ref": {"shopId": self.ref.shop_id, "itemId": self.ref.item_id, "url": self.ref.url},
            "name": self.name,
            "currency": self.currency,
            "variants": [
                {"id": v.id, "name": v.name, "priceCents": v.price_cents, "available": v.available}
                for v in self.variants
            ],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Product":
        ref = value["ref"]
        return cls(
            ProductRef(ref["shopId"], ref["itemId"], ref["url"]),
            value["name"],
            tuple(
                Variant(v["id"], v["name"], v["priceCents"], v["available"])
                for v in value["variants"]
            ),
            value["currency"],
        )


class PriceError(Exception):
    def __init__(self, reason: Reason, message: str):
        super().__init__(message)
        self.reason = reason


class PriceProvider(Protocol):
    async def product(self, ref: ProductRef) -> Product: ...


def money(cents: int) -> str:
    return f"S${cents // 100:,}.{cents % 100:02d}"
