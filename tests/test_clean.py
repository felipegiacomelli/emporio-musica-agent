import csv
from pathlib import Path

from emporio.clean import CLEAN_DIR, clean, description_conflicts, write
from emporio.config import DATA_DIR

RESULT = clean(DATA_DIR)


def rows(table: str) -> list[dict[str, str]]:
    return RESULT.tables[table]


def by_id(table: str, key: str) -> dict[str, dict[str, str]]:
    return {r[key]: r for r in rows(table)}


def test_committed_clean_data_is_up_to_date(tmp_path: Path) -> None:
    write(RESULT, tmp_path)
    for path in sorted(tmp_path.iterdir()):
        committed = CLEAN_DIR / path.name
        assert committed.read_bytes() == path.read_bytes(), path.name
    assert {p.name for p in CLEAN_DIR.iterdir()} == {p.name for p in tmp_path.iterdir()}


def test_conflicting_descriptions_removed() -> None:
    products = by_id("products", "product_id")
    emptied = {int(k) for k, r in products.items() if not r["description"]}
    assert emptied == {135, 137, 139, 140, 142, 144}
    assert products["95"]["description"]  # untouched


def test_kalani_is_not_kala() -> None:
    assert not description_conflicts("Kalani KAL-300S", "Ukulele Kalani soprano")
    assert description_conflicts("Kalani KAL-300S", "Ukulele Kala soprano")


def test_only_active_promotions_one_per_product() -> None:
    promos = rows("promotions")
    assert {int(p["product_id"]) for p in promos} == {90, 94, 121, 127}
    assert len(promos) == 4 and "is_active" not in promos[0]


def test_duplicate_email_cleared_on_customer_without_orders() -> None:
    customers = by_id("customers", "customer_id")
    assert customers["11"]["email"] == "bruno.martins@jmail.com"  # has order 10
    assert customers["43"]["email"] == ""


def test_name_typo_fixed() -> None:
    assert by_id("products", "product_id")["84"]["name"] == (
        "Giannini GN-15 Nylon Cedro Natural"
    )


def test_history_kept_and_reported() -> None:
    orders = by_id("orders", "order_id")
    assert orders["3"]["total_brl"] == "3450"  # kept as recorded
    report = "\n".join(RESULT.kept)
    for fact in ["order 3", "order 20", "order 9", "order 16", "order 18", "136"]:
        assert fact in report, fact


def test_changes_log_lists_every_change() -> None:
    log = (CLEAN_DIR / "CHANGES.md").read_text(encoding="utf-8")
    for fact in ["142", "43", "84", "is_active", "3321-4500"]:
        assert fact in log, fact


def test_clean_csvs_parse() -> None:
    with (CLEAN_DIR / "products.csv").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 65
