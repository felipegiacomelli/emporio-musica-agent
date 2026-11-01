import shutil
from decimal import Decimal
from pathlib import Path

from emporio.config import DATA_DIR
from emporio.data import (
    Product,
    Promotion,
    description_conflicts,
    digits,
    fold,
    load_store,
)

STORE = load_store()
BY_ID: dict[int, Product] = {p.id: p for p in STORE.products}


def test_counts() -> None:
    assert (len(STORE.products), len(STORE.categories), len(STORE.orders)) == (
        65,
        9,
        20,
    )


def test_fold() -> None:
    assert fold("Violão  GD-20!") == "violao gd 20"


def test_digits() -> None:
    assert digits("+55 (67) 99654-7821") == digits("67996547821") == "67996547821"


def test_conflicting_descriptions_dropped() -> None:
    flagged = {p.id for p in STORE.products if p.description is None}
    assert flagged == {135, 137, 139, 140, 142, 144}


def test_kalani_is_not_kala() -> None:
    assert not description_conflicts("Kalani KAL-300S", "Ukulele Kalani soprano")
    assert description_conflicts("Kalani KAL-300S", "Ukulele Kala soprano")


def test_active_promotion_only() -> None:
    assert BY_ID[121].promotion == Promotion(20, "Desconto Exclusivo")
    assert BY_ID[121].final_price == Decimal("439.20")
    assert BY_ID[96].promotion is None  # two inactive rows
    assert BY_ID[93].promotion is None  # two inactive rows
    assert BY_ID[95].final_price == Decimal("2199.00")


def test_highest_active_promotion_wins(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data)
    promos = data / "desafio_tecnico_ai_eng - promotions.csv"
    with promos.open("a", encoding="utf-8") as f:
        f.write("\n26,121,30,Teste,1\n")
    product = {p.id: p for p in load_store(data).products}[121]
    assert product.promotion == Promotion(30, "Teste")
    assert product.final_price == Decimal("384.30")


def test_availability() -> None:
    for pid in (96, 113, 130, 136):
        assert not BY_ID[pid].available, pid
    assert BY_ID[136].stock == 13  # discontinued with stock: still unavailable
    assert BY_ID[95].available


def test_specs_parsed_as_strings() -> None:
    assert BY_ID[142].specs["keys"] == "61"
    assert BY_ID[81].specs["strings"] == "nylon"


def test_empty_categories_kept() -> None:
    used = {p.category.id for p in STORE.products}
    assert {c.id for c in STORE.categories} - used == {6, 7, 8}


def test_order_join() -> None:
    order = STORE.orders[15]
    assert order.customer.id == 18
    assert [i.quantity for i in order.items] == [1, 1]
    assert order.tracking_code is None and order.estimated_delivery is None
    assert STORE.orders[8].tracking_code == "BRJL5544332BR"
    assert STORE.orders[8].items[0].product_name == "Kala KA-C Concert Mogno"
