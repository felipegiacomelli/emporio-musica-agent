import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from emporio.data import load_store
from emporio.rules import _shipping_fee, customer_date
from emporio.tools import run_tool

STORE = load_store()
TODAY = date(2026, 11, 3)


def call(name: str, **args: Any) -> Any:
    return json.loads(run_tool(STORE, name, json.dumps(args), TODAY))


def quote(items: list[tuple[int, int]], **kw: Any) -> Any:
    args = {"items": [{"product_id": p, "quantity": q} for p, q in items]}
    return call("quote_purchase", **args, **kw)


def ret(reason: str, **kw: Any) -> Any:
    return call("check_return", reason=reason, **kw)


# --- quote_purchase -----------------------------------------------------------


def test_quote_installments_12x() -> None:
    q = quote([(95, 1)], installments=12)
    assert q["subtotal"] == "R$ 2.199,00"
    assert q["requested_installments"] == {
        "n": 12,
        "value": "R$ 183,25",
        "allowed": True,
        "minimum": "R$ 100,00",
    }


def test_quote_minimum_installment_tiers() -> None:
    q = quote([(120, 1)], installments=12)  # Kala KA-C 349.90
    assert q["requested_installments"]["allowed"] is False
    assert q["max_installments"] == {"n": 4, "value": "R$ 87,48"}
    assert [o["n"] for o in q["installment_options"]] == [1, 2, 3, 4]


def test_quote_cart_pix_and_free_shipping() -> None:
    q = quote([(81, 1), (120, 1)], delivery_city="campo grande")
    assert q["subtotal"] == "R$ 949,80"
    assert q["pix_total"] == "R$ 902,32"  # per-line rounding: 569.91 + 332.41
    assert q["shipping"]["fee"] == "R$ 0,00"
    assert q["total"] == "R$ 949,80" and q["pix_total_with_shipping"] == "R$ 902,32"
    assert q["split_payment_allowed"] is False


def test_quote_pix_never_stacks_on_promotion() -> None:
    q = quote([(121, 2)])  # Ohana CK-20, 20% off
    assert q["lines"][0]["unit_final_price"] == "R$ 439,20"
    assert q["pix_total"] == q["subtotal"] == "R$ 878,40"


def test_quote_shipping_fee_below_500_and_other_city() -> None:
    assert (
        quote([(120, 1)], delivery_city="Campo Grande")["shipping"]["fee"] == "R$ 35,00"
    )
    q = quote([(120, 1)], delivery_city="Campo Grande")
    assert q["total"] == "R$ 384,90"
    other = quote([(81, 1)], delivery_city="Dourados")
    assert other["shipping"]["fee"] is None and "CEP" in other["shipping"]["note"]
    assert other["total"] is None
    assert quote([(81, 1)])["shipping"]["fee"] is None


def test_quote_split_payment_over_2000() -> None:
    assert quote([(95, 1)])["split_payment_allowed"] is True


def test_quote_rejects_unavailable_and_unknown() -> None:
    assert "indisponível" in quote([(96, 1)])["error"]
    assert "descontinuado" in quote([(136, 1)])["error"]
    assert "999" in quote([(999, 1)])["error"]
    assert "error" in quote([])
    assert "error" in quote([(95, 0)])


# --- check_return -------------------------------------------------------------


def test_regret_in_window_by_date() -> None:
    r = ret(
        "arrependimento",
        channel="online",
        received_on="2026-10-30",
        used=False,
        original_packaging=True,
    )
    assert r["decision"] == "pode_solicitar" and r["rule"] == "§4.1"
    assert r["days_since_receipt"] == 4
    assert "3341-4444" in r["next_step"]


def test_regret_out_of_window() -> None:
    r = ret("arrependimento", channel="online", received_on="2026-10-25")
    assert r["decision"] == "fora_da_politica"
    assert r["days_since_receipt"] == 9
    assert any("7 dias" in reason for reason in r["reasons"])


def test_regret_missing_facts() -> None:
    r = ret("arrependimento")
    assert r["decision"] == "faltam_dados"
    assert len(r["missing"]) == 4


def test_regret_in_store_purchase_not_covered() -> None:
    r = ret("arrependimento", channel="loja", days_since_receipt=2)
    assert r["decision"] == "fora_da_politica" and "§4.3" in r["alternative"]


def test_regret_used_product() -> None:
    r = ret(
        "arrependimento",
        channel="online",
        days_since_receipt=2,
        used=True,
        original_packaging=True,
    )
    assert r["decision"] == "fora_da_politica"


def test_defect_within_30_days_of_purchase() -> None:
    r = ret("defeito", purchased_on="2026-10-20")
    assert r["decision"] == "pode_solicitar" and r["rule"] == "§4.2"
    assert any("mau uso" in c for c in r["conditions"])


def test_defect_after_30_days_goes_to_warranty() -> None:
    r = ret("defeito", days_since_purchase=45, days_since_receipt=40)
    assert r["decision"] == "fora_da_politica"
    assert "fabricante" in r["alternative"] and "90 dias" in r["alternative"]


def test_preference_rules() -> None:
    ok = ret("preferencia", days_since_receipt=3, used=False, original_packaging=True)
    assert ok["decision"] == "pode_solicitar" and ok["rule"] == "§4.3"
    custom = ret(
        "preferencia",
        days_since_receipt=3,
        used=False,
        original_packaging=True,
        customized=True,
    )
    assert custom["decision"] == "fora_da_politica"


@pytest.mark.parametrize(
    "args",
    [
        {"reason": "troca"},
        {"reason": "arrependimento", "received_on": "2026-12-01"},  # future
        {"reason": "arrependimento", "received_on": "31/02"},  # no such day
        {"reason": "arrependimento", "received_on": "ontem"},
    ],
)
def test_check_return_bad_args(args: dict[str, Any]) -> None:
    assert "error" in call("check_return", **args)


def test_rule_summary_explains_the_rule() -> None:
    assert "7 dias" in ret("arrependimento")["rule_summary"]
    assert "30 dias" in ret("defeito")["rule_summary"]
    assert "venda final" in ret("preferencia")["rule_summary"]


def test_shipping_threshold_is_strictly_above_500() -> None:
    # "acima de R$ 500,00" read strictly: exactly 500 pays the R$ 35 fee
    assert _shipping_fee("Campo Grande", Decimal("500.00")) == Decimal(35)
    assert _shipping_fee("Campo Grande", Decimal("500.01")) == Decimal(0)
    assert _shipping_fee("Dourados", Decimal("900")) is None


def test_quantity_over_stock_and_duplicate_lines() -> None:
    assert "estoque insuficiente" in quote([(95, 6)])["error"]  # stock 5
    stock = STORE.product(95).stock  # type: ignore[union-attr]
    # the same product split over two lines is checked against stock as one
    assert "estoque insuficiente" in quote([(95, stock), (95, 1)])["error"]
    merged = quote([(81, 1), (81, 1)])
    assert len(merged["lines"]) == 1 and merged["lines"][0]["quantity"] == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("25/10", date(2026, 10, 25)),
        ("28/12", date(2025, 12, 28)),  # no year, would be future -> last year
        ("25/10/2026", date(2026, 10, 25)),
        ("25/10/26", date(2026, 10, 25)),
        ("2026-10-25", date(2026, 10, 25)),
    ],
)
def test_customer_date(text: str, expected: date) -> None:
    assert customer_date(text, TODAY) == expected


def test_return_with_customer_date_format() -> None:
    r = ret("arrependimento", channel="online", received_on="25/10")
    assert r["days_since_receipt"] == 9 and r["decision"] == "fora_da_politica"
