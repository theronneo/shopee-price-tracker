"""Durable watches and transactional observation/notification persistence."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .domain import Product, ProductRef, Reason, Variant


@dataclass(frozen=True)
class Watch:
    id: int
    ref: ProductRef
    name: str
    variant_id: str
    variant_name: str
    last_price: int | None
    last_checked: int
    next_check: int
    status: str
    access_incident: bool


@dataclass(frozen=True)
class Notification:
    id: int
    watch_id: int
    kind: Literal["drop", "access"]
    previous_cents: int | None
    price_cents: int | None
    created_at: int
    attempts: int
    name: str
    variant_name: str
    url: str


def _watch(row: sqlite3.Row) -> Watch:
    return Watch(
        row["id"],
        ProductRef(row["shopId"], row["itemId"], row["url"]),
        row["name"],
        row["variantId"],
        row["variantName"],
        row["lastPrice"],
        row["lastChecked"],
        row["nextCheck"],
        row["status"],
        bool(row["accessIncident"]),
    )


def _valid_id(value: int) -> bool:
    return type(value) is int and 0 < value < 2**63


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self.db.close()
            raise ValueError(f"Unsupported database version {version}.")
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY, shopId TEXT NOT NULL, itemId TEXT NOT NULL,
                url TEXT NOT NULL, name TEXT NOT NULL, variantId TEXT NOT NULL,
                variantName TEXT NOT NULL, lastPrice INTEGER, lastChecked INTEGER NOT NULL,
                nextCheck INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'ok',
                active INTEGER NOT NULL DEFAULT 1, accessIncident INTEGER NOT NULL DEFAULT 0
            );
            CREATE UNIQUE INDEX IF NOT EXISTS active_variant
                ON watches(shopId,itemId,variantId) WHERE active=1;
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, watchId INTEGER NOT NULL REFERENCES watches(id),
                priceCents INTEGER NOT NULL CHECK(priceCents>0), observedAt INTEGER NOT NULL,
                UNIQUE(watchId,observedAt)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY, watchId INTEGER NOT NULL REFERENCES watches(id),
                kind TEXT NOT NULL, previousCents INTEGER, priceCents INTEGER,
                createdAt INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                nextAttempt INTEGER NOT NULL, sent INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS selections (
                token TEXT PRIMARY KEY, product TEXT NOT NULL, expiresAt INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
        """)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def close(self) -> None:
        self.db.close()

    def list_watches(self) -> list[Watch]:
        return [
            _watch(row)
            for row in self.db.execute("SELECT * FROM watches WHERE active=1 ORDER BY id")
        ]

    def get_watch(self, watch_id: int) -> Watch | None:
        if not _valid_id(watch_id):
            return None
        row = self.db.execute(
            "SELECT * FROM watches WHERE id=? AND active=1", (watch_id,)
        ).fetchone()
        return _watch(row) if row else None

    def find_watch(self, ref: ProductRef, variant_id: str) -> Watch | None:
        row = self.db.execute(
            "SELECT * FROM watches WHERE shopId=? AND itemId=? AND variantId=? AND active=1",
            (ref.shop_id, ref.item_id, variant_id),
        ).fetchone()
        return _watch(row) if row else None

    def due(self, now: int) -> list[Watch]:
        return [
            _watch(row)
            for row in self.db.execute(
                "SELECT * FROM watches WHERE active=1 AND nextCheck<=? ORDER BY nextCheck,id",
                (now,),
            )
        ]

    def add_watch(self, product: Product, variant: Variant, now: int, interval: int) -> Watch:
        with self._transaction():
            existing = self.find_watch(product.ref, variant.id)
            if existing:
                return existing
            price = variant.price_cents if variant.available else None
            if price is not None:
                self._validate_price(price)
            result = self.db.execute(
                """INSERT INTO watches
                (shopId,itemId,url,name,variantId,variantName,lastPrice,lastChecked,nextCheck,status)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    product.ref.shop_id,
                    product.ref.item_id,
                    product.ref.url,
                    product.name,
                    variant.id,
                    variant.name,
                    price,
                    now,
                    now + interval,
                    "ok" if price else "unavailable",
                ),
            )
            watch_id = result.lastrowid
            assert watch_id is not None
            if price is not None:
                self.db.execute(
                    "INSERT INTO observations(watchId,priceCents,observedAt) VALUES(?,?,?)",
                    (watch_id, price, now),
                )
            watch = self.get_watch(watch_id)
            assert watch is not None
            return watch

    @staticmethod
    def _validate_price(price: int) -> None:
        if type(price) is not int or not 0 < price < 2**63:
            raise ValueError("Invalid price in cents.")

    def observe(self, watch_id: int, price: int, now: int, interval: int) -> None:
        self._validate_price(price)
        with self._transaction():
            watch = self.get_watch(watch_id)
            if not watch or now <= watch.last_checked:
                return
            self.db.execute(
                "INSERT INTO observations(watchId,priceCents,observedAt) VALUES(?,?,?)",
                (watch_id, price, now),
            )
            if watch.last_price is not None and price < watch.last_price:
                self.db.execute(
                    """INSERT INTO notifications
                    (watchId,kind,previousCents,priceCents,createdAt,nextAttempt)
                    VALUES(?,'drop',?,?,?,?)""",
                    (watch_id, watch.last_price, price, now, now),
                )
            self.db.execute(
                "UPDATE watches SET lastPrice=?,lastChecked=?,nextCheck=?,status='ok',accessIncident=0 WHERE id=?",
                (price, now, now + interval, watch_id),
            )
            self.db.execute(
                "DELETE FROM notifications WHERE watchId=? AND kind='access' AND sent=0",
                (watch_id,),
            )

    def fail_watch(self, watch_id: int, reason: Reason, now: int, interval: int) -> None:
        with self._transaction():
            watch = self.get_watch(watch_id)
            if not watch or now <= watch.last_checked:
                return
            if reason == "access" and not watch.access_incident:
                self.db.execute(
                    "INSERT INTO notifications(watchId,kind,createdAt,nextAttempt) VALUES(?,'access',?,?)",
                    (watch_id, now, now),
                )
            self.db.execute(
                "UPDATE watches SET status=?,lastChecked=?,nextCheck=?,accessIncident=? WHERE id=?",
                (
                    reason,
                    now,
                    now + interval,
                    int(reason == "access" or watch.access_incident),
                    watch_id,
                ),
            )

    def untrack(self, watch_id: int) -> bool:
        if not _valid_id(watch_id):
            return False
        with self._transaction():
            result = self.db.execute(
                "UPDATE watches SET active=0 WHERE id=? AND active=1", (watch_id,)
            )
            self.db.execute("DELETE FROM notifications WHERE watchId=? AND sent=0", (watch_id,))
            return result.rowcount > 0

    def pending(self, now: int) -> list[Notification]:
        if self._get_number("deliveryResume") > now:
            return []
        rows = self.db.execute(
            """SELECT n.*,w.name,w.variantName,w.url
            FROM notifications n JOIN watches w ON w.id=n.watchId
            WHERE n.sent=0 AND n.nextAttempt<=? AND w.active=1 ORDER BY n.id""",
            (now,),
        )
        return [
            Notification(
                row["id"],
                row["watchId"],
                row["kind"],
                row["previousCents"],
                row["priceCents"],
                row["createdAt"],
                row["attempts"],
                row["name"],
                row["variantName"],
                row["url"],
            )
            for row in rows
        ]

    def mark_sent(self, notification_id: int) -> None:
        self.db.execute("UPDATE notifications SET sent=1 WHERE id=?", (notification_id,))

    def retry_notification(self, notification_id: int, now: int, delay: int) -> None:
        self.db.execute(
            "UPDATE notifications SET attempts=attempts+1,nextAttempt=? WHERE id=?",
            (now + delay, notification_id),
        )

    def defer_delivery(self, until: int) -> None:
        self._set_number("deliveryResume", max(until, self._get_number("deliveryResume")))

    def delivery_resume(self) -> int:
        return self._get_number("deliveryResume")

    def save_selection(self, update_id: int, product: Product, now: int) -> str:
        token = str(update_id)
        with self._transaction():
            self.db.execute("DELETE FROM selections WHERE expiresAt<=?", (now,))
            self.db.execute(
                "INSERT OR IGNORE INTO selections(token,product,expiresAt) VALUES(?,?,?)",
                (token, json.dumps(product.to_dict()), now + 86400),
            )
        return token

    def selection(self, token: str, now: int) -> Product | None:
        row = self.db.execute(
            "SELECT product FROM selections WHERE token=? AND expiresAt>?", (token, now)
        ).fetchone()
        return Product.from_dict(json.loads(row["product"])) if row else None

    def delete_selection(self, token: str) -> None:
        self.db.execute("DELETE FROM selections WHERE token=?", (token,))

    def _get_number(self, key: str) -> int:
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return int(row["value"]) if row else 0

    def _set_number(self, key: str, value: int) -> None:
        self.db.execute(
            "INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def offset(self) -> int:
        return self._get_number("offset")

    def set_offset(self, value: int) -> None:
        self._set_number("offset", value)
