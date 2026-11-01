"""Load the cleaned store data (data/clean/) once into immutable objects.

Cleaning happens offline in emporio/clean.py; this module trusts its output.
"""

import csv
import json
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from attrs import frozen

from emporio.clean import CLEAN_DIR

CENT = Decimal("0.01")


def fold(text: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumerics to single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", plain.casefold()).strip()


def digits(text: str) -> str:
    """Phone digits only, without the +55 country code."""
    only = re.sub(r"\D", "", text)
    return only[2:] if len(only) == 13 and only.startswith("55") else only


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@frozen
class Category:
    id: int
    name: str


@frozen
class Promotion:
    percent: int
    name: str


@frozen
class Product:
    id: int
    name: str
    category: Category
    price: Decimal
    stock: int
    status: str
    specs: dict[str, str]
    description: str | None
    promotion: Promotion | None

    @property
    def final_price(self) -> Decimal:
        if self.promotion is None:
            return money(self.price)
        return money(self.price * (100 - self.promotion.percent) / 100)

    @property
    def available(self) -> bool:
        return self.status == "active" and self.stock > 0


@frozen
class Customer:
    id: int
    name: str
    phone: str
    email: str | None


@frozen
class OrderItem:
    product_name: str
    quantity: int


@frozen
class Order:
    id: int
    customer: Customer
    order_date: date
    status: str
    total: Decimal
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: tuple[OrderItem, ...]


@frozen
class Store:
    categories: tuple[Category, ...]
    products: tuple[Product, ...]
    orders: dict[int, Order]

    def product(self, product_id: int) -> Product | None:
        return next((p for p in self.products if p.id == product_id), None)


def _rows(data_dir: Path, table: str) -> list[dict[str, str]]:
    with (data_dir / f"{table}.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def load_store(data_dir: Path = CLEAN_DIR) -> Store:
    categories = {
        int(r["category_id"]): Category(int(r["category_id"]), r["name"])
        for r in _rows(data_dir, "categories")
    }
    promotions = {
        int(r["product_id"]): Promotion(int(r["discount_percent"]), r["description"])
        for r in _rows(data_dir, "promotions")
    }
    products = tuple(
        Product(
            id=int(r["product_id"]),
            name=r["name"],
            category=categories[int(r["category_id"])],
            price=Decimal(r["price_brl"]),
            stock=int(r["stock_quantity"]),
            status=r["status"],
            specs={k: str(v) for k, v in json.loads(r["specs"]).items()},
            description=r["description"] or None,
            promotion=promotions.get(int(r["product_id"])),
        )
        for r in _rows(data_dir, "products")
    )
    names = {p.id: p.name for p in products}
    customers = {
        int(r["customer_id"]): Customer(
            int(r["customer_id"]), r["name"], r["phone"], r["email"] or None
        )
        for r in _rows(data_dir, "customers")
    }
    items: dict[int, list[OrderItem]] = {}
    for r in _rows(data_dir, "order_items"):
        items.setdefault(int(r["order_id"]), []).append(
            OrderItem(names[int(r["product_id"])], int(r["quantity"]))
        )
    orders = {
        int(r["order_id"]): Order(
            id=int(r["order_id"]),
            customer=customers[int(r["customer_id"])],
            order_date=date.fromisoformat(r["order_date"]),
            status=r["status"],
            total=Decimal(r["total_brl"]),
            payment_method=r["payment_method"],
            tracking_code=r["tracking_code"] or None,
            estimated_delivery=_date(r["estimated_delivery"]),
            notes=r["notes"] or None,
            items=tuple(items.get(int(r["order_id"]), ())),
        )
        for r in _rows(data_dir, "orders")
    }
    return Store(tuple(categories.values()), products, orders)
