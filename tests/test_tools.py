import json
from datetime import date
from typing import Any

from emporio.data import load_store
from emporio.tools import NOT_FOUND, TOOL_SCHEMAS, run_tool

STORE = load_store()
TODAY = date(2026, 11, 3)


def call(name: str, **args: Any) -> Any:
    return json.loads(run_tool(STORE, name, json.dumps(args), TODAY))


def search(**args: Any) -> Any:
    return call("search_products", **args)


def ids_of(**args: Any) -> set[int]:
    return {r["id"] for r in search(**args)["results"]}


def one(**args: Any) -> Any:
    results = search(**args)["results"]
    assert len(results) == 1, results
    return results[0]


def order(order_id: int, contact: str) -> Any:
    return call("get_order", order_id=order_id, email_or_phone=contact)


def test_search_by_name_variants() -> None:
    for q in ["Takamine GD20", "takamine gd-20", "TAKAMINE gd 20"]:
        assert [r["id"] for r in search(query=q)["results"]] == [95], q


def test_instrument_word_in_query() -> None:
    results = search(query="violao yamaha")["results"]
    assert {81, 82, 92, 98}.issubset({r["id"] for r in results})
    assert all(r["category"] == "Violões" for r in results)


def test_violoes_ate_1000_excludes_unavailable() -> None:
    res = search(category="Violões", max_price=1000)
    ids = {r["id"] for r in res["results"]}
    # 12 available ≤1000 (cheapest 83 @429.90 … 112 @999); 96 (stock 0) and
    # 113 (discontinued) excluded; results sorted by final price
    assert {83, 85, 81}.issubset(ids) and not {96, 113} & ids
    assert len(ids) == 10 and res["more"] == 2
    prices = [float(r["final_price"]) for r in res["results"]]
    assert prices == sorted(prices)


def test_include_unavailable_shows_status() -> None:
    r = one(query="Giannini GF-3D", include_unavailable=True)
    assert r["available"] is False and r["stock"] == 0
    assert search(query="Giannini GF-3D")["results"] == []


def test_promo_rendering() -> None:
    r = one(query="Ohana CK-20")
    assert r["price"] == "549.00" and r["final_price"] == "439.20"
    assert r["promotion"] == {"percent": 20, "name": "Desconto Exclusivo"}
    assert r["pix_price"] is None  # §6.2: PIX never stacks on a promotion
    gd20 = one(query="Takamine GD20")
    assert gd20["promotion"] is None and gd20["pix_price"] == "2089.05"
    assert one(query="Yamaha C40")["pix_price"] == "569.91"  # 569.905 rounds up


def test_max_price_uses_final_price() -> None:
    # Ohana CK-20: 549.00 list, 439.20 with the active promotion
    assert 121 in ids_of(max_price=440)


def test_on_promotion_lists_exactly_active() -> None:
    assert ids_of(on_promotion=True) == {90, 94, 121, 127}


def test_description_never_searched() -> None:
    assert 142 not in ids_of(query="Roland", include_unavailable=True)


def test_conflicting_description_hidden() -> None:
    r = one(query="Korg Synth 1", include_unavailable=True)
    assert r["description"] is None and r["specs"]["keys"] == "61"


def test_empty_category_returns_nothing() -> None:
    assert search(category="Instrumentos de Sopro (Metais)")["results"] == []


def test_order_by_email_and_phone_variants() -> None:
    for contact in [
        "anacarol.ferreira@coldmail.com",
        "ANACAROL.FERREIRA@coldmail.com ",
        "(67) 99654-7821",
        "67996547821",
        "+55 67 99654-7821",
    ]:
        assert order(8, contact)["status"] == "shipped", contact


def test_order_fields_and_overdue() -> None:
    o = order(8, "67996547821")
    assert o["status_pt"] == "enviado" and o["delivery_overdue"] is True
    assert o["estimated_delivery"] == "2026-02-28"
    assert o["tracking_code"] == "BRJL5544332BR"
    assert o["items"] == [{"name": "Kala KA-C Concert Mogno", "quantity": 1}]
    assert o["total"] == "349.90"
    assert order(1, "pedro.oliveira@jmail.com")["delivery_overdue"] is False


def test_rejected_lookup_leaks_nothing() -> None:
    for oid, contact in [(8, "lucas.mendes@jmail.com"), (999, "x@y.z")]:
        args = json.dumps({"order_id": oid, "email_or_phone": contact})
        out = run_tool(STORE, "get_order", args, TODAY)
        assert json.loads(out) == {"error": NOT_FOUND}
        for leak in ["Ana", "349.9", "BRJL5544332BR", "Kala", "shipped"]:
            assert leak not in out


def test_customer_pii_minimal() -> None:
    o = order(8, "67996547821")
    dumped = json.dumps(o)
    assert o["customer_first_name"] == "Ana"
    assert "coldmail" not in dumped and "99654" not in dumped
    assert "Ferreira" not in dumped


def test_run_tool_bad_inputs_return_error() -> None:
    for name, args in [
        ("get_order", '{"order_id": "#8", "email_or_phone": "x@y.z"}'),
        ("get_order", '{"order_id": 8}'),
        ("search_products", '{"category": "Pianos de cauda"}'),
        ("search_products", '{"max_price": -5}'),
        ("search_products", '{"unknown": 1}'),
        ("nope", "{}"),
        ("search_products", "not json"),
        ("search_products", "[1, 2]"),
    ]:
        out = json.loads(run_tool(STORE, name, args, TODAY))
        assert set(out) == {"error"}, (name, args)


def test_strict_nulls_accepted() -> None:
    # strict mode sends every property, unused ones as null
    res = search(
        query="Ohana CK-20",
        category=None,
        max_price=None,
        on_promotion=False,
        include_unavailable=False,
    )
    assert [r["id"] for r in res["results"]] == [121]


def test_schemas_are_strict_and_complete() -> None:
    for tool in TOOL_SCHEMAS:
        params: Any = tool["parameters"]
        assert tool["strict"] is True and tool["type"] == "function"
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"])
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert names == {"search_products", "get_order", "quote_purchase", "check_return"}


def test_unavailable_reason() -> None:
    reasons = {
        pid: one(query=q, include_unavailable=True)["unavailable_reason"]
        for pid, q in [(96, "Giannini GF-3D"), (136, "Ibanez Bass 2X"), (130, "KA-ABP")]
    }
    assert reasons == {96: "sem estoque", 136: "descontinuado", 130: "em breve"}
    assert one(query="Takamine GD20")["unavailable_reason"] is None


def test_empty_result_notes() -> None:
    empty_cat = search(category="Instrumentos de Sopro (Metais)")
    assert "não tem nenhum produto" in empty_cat["note"]
    only_unavailable = search(query="Giannini GF-3D")
    assert "indisponíveis" in only_unavailable["note"]
    nothing = search(query="Di Giorgio")
    assert nothing["note"] == "Nenhum produto do catálogo corresponde à busca."
    assert "note" not in search(query="Takamine GD20")
