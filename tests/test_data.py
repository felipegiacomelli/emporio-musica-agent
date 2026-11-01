from decimal import Decimal

from emporio.data import Product, Promotion, digits, fold, load_store

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


def test_active_promotion_only() -> None:
    assert BY_ID[121].promotion == Promotion(20, "Desconto Exclusivo")
    assert BY_ID[121].final_price == Decimal("439.20")
    assert BY_ID[96].promotion is None  # two inactive rows
    assert BY_ID[93].promotion is None  # two inactive rows
    assert BY_ID[95].final_price == Decimal("2199.00")


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


def test_clean_data_loaded() -> None:
    assert BY_ID[142].description is None and BY_ID[95].description
    assert BY_ID[84].name == "Giannini GN-15 Nylon Cedro Natural"
    assert STORE.orders[10].customer.email == "bruno.martins@jmail.com"
    assert STORE.product(95) is BY_ID[95] and STORE.product(999) is None
