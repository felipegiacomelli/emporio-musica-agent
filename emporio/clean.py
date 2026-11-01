"""Clean the raw challenge CSVs into data/clean/, logging every change.

Usage: uv run python -m emporio.clean

The raw files in data/ stay exactly as given. The agent loads only
data/clean/. Records of past orders that disagree with the policy are kept
as recorded and listed in the report: they are history, not broken data.
"""

import csv
import io
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from attrs import frozen

from emporio.config import DATA_DIR

CLEAN_DIR = DATA_DIR / "clean"
TABLES = ["categories", "products", "promotions", "customers", "orders", "order_items"]

BRANDS = frozenset(
    {
        "Yamaha", "Kala", "Kalani", "Tagima", "Giannini", "Shelby", "Takamine",
        "Ohana", "Rozini", "Crafter", "Martin", "Taylor", "Fender", "Ibanez",
        "Music Man", "Gibson", "PRS", "Pearl", "Korg", "Nord", "Roland", "Tama",
    }
)  # fmt: skip
_BRAND_RE = {b: re.compile(rf"\b{re.escape(b)}\b", re.IGNORECASE) for b in BRANDS}

# Hand fixes: each one is listed in CHANGES.md.
NAME_FIXES = {
    "84": ("Giannini GN-15 Nylon Cedr Natural", "Giannini GN-15 Nylon Cedro Natural"),
}

# Edits made by hand to emporio/policy.md (the PDF stays as given).
POLICY_EDITS = [
    "§1.2 e-mail `contato@empóriodamusica.com.br` → `contato@emporiodamusica.com.br`"
    " (the cover page spells it without the accent).",
    "§7 WhatsApp `(67) 3321-4500` → `(67) 3341-4444` (cover page and §1.2 agree"
    " on 3341-4444).",
    "§3 credit-card row `Parcela mínima de R$ 100,00` → `Parcela mínima conforme"
    " §3.1` (§3.1 has the detailed tiers; the table contradicted them).",
    "§3.1 `sem valor mínimo de parcela (exceto abaixo de R$ 50,00)` → `parcela"
    " mínima de R$ 50,00` (the original wording contradicts itself).",
]

MIN_INSTALLMENT = [(3, Decimal(50)), (6, Decimal(80)), (12, Decimal(100))]


def description_conflicts(name: str, description: str) -> bool:
    """True when the description names a brand the product name does not."""
    in_name = {b for b, rx in _BRAND_RE.items() if rx.search(name)}
    in_desc = {b for b, rx in _BRAND_RE.items() if rx.search(description)}
    return bool(in_desc - in_name)


@frozen
class CleanResult:
    tables: dict[str, list[dict[str, str]]]
    changes: list[str]
    kept: list[str]


def _read(raw_dir: Path, table: str) -> list[dict[str, str]]:
    path = raw_dir / f"desafio_tecnico_ai_eng - {table}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return [
            {k: v.strip() for k, v in row.items()}
            for row in csv.DictReader(f)
            if any(row.values())
        ]


def clean(raw_dir: Path = DATA_DIR) -> CleanResult:
    t = {name: _read(raw_dir, name) for name in TABLES}
    changes: list[str] = []
    kept: list[str] = []
    products = {p["product_id"]: p for p in t["products"]}

    for p in t["products"]:
        if p["description"] and description_conflicts(p["name"], p["description"]):
            changes.append(
                f"product {p['product_id']} ({p['name']}): description removed, it"
                f" names another brand: {p['description']!r}"
            )
            p["description"] = ""
        if p["product_id"] in NAME_FIXES:
            old, new = NAME_FIXES[p["product_id"]]
            if p["name"] == old:
                p["name"] = new
                changes.append(f"product {p['product_id']}: name {old!r} → {new!r}")

    active: dict[str, dict[str, str]] = {}
    for r in t["promotions"]:
        if r["is_active"] != "1":
            continue
        best = active.get(r["product_id"])
        if best is None or int(r["discount_percent"]) > int(best["discount_percent"]):
            active[r["product_id"]] = r
    dropped = len(t["promotions"]) - len(active)
    changes.append(
        f"promotions: {dropped} rows with is_active=0 removed; {len(active)} active"
        " kept (one per product), column is_active dropped"
    )
    t["promotions"] = [
        {k: v for k, v in r.items() if k != "is_active"} for r in active.values()
    ]

    with_orders = {o["customer_id"] for o in t["orders"]}
    emails = Counter(c["email"].casefold() for c in t["customers"])
    for c in t["customers"]:
        if emails[c["email"].casefold()] > 1 and c["customer_id"] not in with_orders:
            changes.append(
                f"customer {c['customer_id']}: e-mail {c['email']} cleared, it"
                " duplicates another customer's and this customer has no orders"
            )
            c["email"] = ""

    items: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for i in t["order_items"]:
        items[i["order_id"]].append(i)
    for o in t["orders"]:
        lines = items[o["order_id"]]
        total = sum(
            (
                Decimal(products[i["product_id"]]["price_brl"]) * int(i["quantity"])
                for i in lines
            ),
            Decimal(0),
        )
        if total != Decimal(o["total_brl"]):
            kept.append(
                f"order {o['order_id']} ({o['status']}): total {o['total_brl']} ≠"
                f" items at current prices {total}; recorded total kept"
            )
        m = re.fullmatch(r"credit_(\d+)x", o["payment_method"])
        if m:
            n = int(m.group(1))
            minimum = next(v for limit, v in MIN_INSTALLMENT if n <= limit)
            if Decimal(o["total_brl"]) / n < minimum:
                kept.append(
                    f"order {o['order_id']}: {n}x of"
                    f" {Decimal(o['total_brl']) / n:.2f} is below the §3.1 minimum"
                    f" {minimum}; past order kept"
                )
        for i in lines:
            status = products[i["product_id"]]["status"]
            if status != "active":
                kept.append(
                    f"order {o['order_id']}: contains product {i['product_id']}"
                    f" with status {status}; past order kept"
                )
    for p in t["products"]:
        if p["status"] != "active" and p["stock_quantity"] != "0":
            kept.append(
                f"product {p['product_id']} ({p['name']}): status {p['status']} with"
                f" stock {p['stock_quantity']}; status wins (not sold)"
            )
    for p in t["products"]:
        json.loads(p["specs"])  # fail loudly on malformed specs
    return CleanResult(t, changes, kept)


def _csv(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def write(result: CleanResult, out_dir: Path = CLEAN_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in result.tables.items():
        (out_dir / f"{name}.csv").write_text(_csv(rows), encoding="utf-8")
    log = [
        "# Data cleaning log",
        "",
        "Generated by `uv run python -m emporio.clean` from the raw files in"
        " `data/`. Do not edit by hand.",
        "",
        "## Changes to the data",
        "",
        *(f"- {c}" for c in result.changes),
        "",
        "## Kept as recorded (history, not broken data)",
        "",
        *(f"- {k}" for k in result.kept),
        "",
        "## Edits to the policy text (`emporio/policy.md`)",
        "",
        *(f"- {e}" for e in POLICY_EDITS),
        "",
    ]
    (out_dir / "CHANGES.md").write_text("\n".join(log), encoding="utf-8")


if __name__ == "__main__":
    write(clean())
    print(f"wrote {CLEAN_DIR}")
