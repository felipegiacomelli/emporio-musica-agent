"""Load the store CSVs once into immutable objects.

Data-quality rules applied here (documented in the README):
- only promotions with ``is_active=1`` count; if several are active, the
  highest percent wins;
- a product description that names a brand other than the product's own is
  treated as unreliable and dropped (name > specs > description).
"""

import csv
import json
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from attrs import frozen

from emporio.config import DATA_DIR

BRANDS = frozenset(
    {
        "Yamaha", "Kala", "Kalani", "Tagima", "Giannini", "Shelby", "Takamine",
        "Ohana", "Rozini", "Crafter", "Martin", "Taylor", "Fender", "Ibanez",
        "Music Man", "Gibson", "PRS", "Pearl", "Korg", "Nord", "Roland", "Tama",
    }
)  # fmt: skip
_BRAND_RE = {b: re.compile(rf"\b{re.escape(b)}\b", re.IGNORECASE) for b in BRANDS}
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


def description_conflicts(name: str, description: str) -> bool:
    """True when the description names a brand the product name does not."""
    in_name = {b for b, rx in _BRAND_RE.items() if rx.search(name)}
    in_desc = {b for b, rx in _BRAND_RE.items() if rx.search(description)}
    return bool(in_desc - in_name)


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
    email: str


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


def _rows(data_dir: Path, table: str) -> list[dict[str, str | None]]:
    path = data_dir / f"desafio_tecnico_ai_eng - {table}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return [
            {k: (v.strip() or None) for k, v in row.items()}
            for row in csv.DictReader(f)
            if any(row.values())
        ]


def _req(row: dict[str, str | None], key: str) -> str:
    value = row[key]
    if value is None:
        raise ValueError(f"missing {key!r} in {row}")
    return value


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def load_store(data_dir: Path = DATA_DIR) -> Store:
    categories = {
        int(_req(r, "category_id")): Category(
            int(_req(r, "category_id")), _req(r, "name")
        )
        for r in _rows(data_dir, "categories")
    }

    promotions: dict[int, Promotion] = {}
    for r in _rows(data_dir, "promotions"):
        if r["is_active"] != "1":
            continue
        pid = int(_req(r, "product_id"))
        promo = Promotion(int(_req(r, "discount_percent")), _req(r, "description"))
        if pid not in promotions or promo.percent > promotions[pid].percent:
            promotions[pid] = promo

    products = []
    for r in _rows(data_dir, "products"):
        pid, name = int(_req(r, "product_id")), _req(r, "name")
        description = r["description"]
        if description and description_conflicts(name, description):
            description = None
        products.append(
            Product(
                id=pid,
                name=name,
                category=categories[int(_req(r, "category_id"))],
                price=Decimal(_req(r, "price_brl")),
                stock=int(_req(r, "stock_quantity")),
                status=_req(r, "status"),
                specs={k: str(v) for k, v in json.loads(r["specs"] or "{}").items()},
                description=description,
                promotion=promotions.get(pid),
            )
        )
    names = {p.id: p.name for p in products}

    customers = {
        int(_req(r, "customer_id")): Customer(
            int(_req(r, "customer_id")),
            _req(r, "name"),
            _req(r, "phone"),
            _req(r, "email"),
        )
        for r in _rows(data_dir, "customers")
    }

    items: dict[int, list[OrderItem]] = {}
    for r in _rows(data_dir, "order_items"):
        items.setdefault(int(_req(r, "order_id")), []).append(
            OrderItem(names[int(_req(r, "product_id"))], int(_req(r, "quantity")))
        )

    orders = {}
    for r in _rows(data_dir, "orders"):
        oid = int(_req(r, "order_id"))
        orders[oid] = Order(
            id=oid,
            customer=customers[int(_req(r, "customer_id"))],
            order_date=date.fromisoformat(_req(r, "order_date")),
            status=_req(r, "status"),
            total=Decimal(_req(r, "total_brl")),
            payment_method=_req(r, "payment_method"),
            tracking_code=r["tracking_code"],
            estimated_delivery=_date(r["estimated_delivery"]),
            notes=r["notes"],
            items=tuple(items.get(oid, ())),
        )

    return Store(tuple(categories.values()), tuple(products), orders)
