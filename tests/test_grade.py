from decimal import Decimal as D
from pathlib import Path

import pytest

from emporio.agent import FALLBACK
from evals.grade import Case, extract_prices, grade, load_cases

VERSION, CASES = load_cases(Path(__file__).parent.parent / "evals" / "cases.toml")
BY_ID = {c.id: c for c in CASES}


def test_case_set_shape() -> None:
    assert VERSION == 7 and len(CASES) == 31
    assert len(BY_ID) == len(CASES)  # unique ids


@pytest.mark.parametrize(
    ("case", "index"),
    [(c, i) for c in CASES for i in range(len(c.bad))],
    ids=lambda v: v.id if isinstance(v, Case) else str(v),
)
def test_grader_rejects_bad_fixture(case: Case, index: int) -> None:
    bad = case.bad[index]
    assert not grade(case, bad.replies, bad.tool_calls).passed


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_grader_accepts_good_fixture(case: Case) -> None:
    for good in case.good:
        result = grade(case, good.replies, good.tool_calls)
        assert result.passed, result.failures


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_grader_rejects_empty_reply(case: Case) -> None:
    assert not grade(case, [""] * len(case.turns), []).passed


def test_extract_prices() -> None:
    text = "R$ 2.199,00, 439.20 ou 569,91; 12x de R$ 100 em 03/11/2026, 20%"
    assert extract_prices(text) == {
        D("2199.00"),
        D("439.20"),
        D("569.91"),
        D("100.00"),
    }
    assert extract_prices("R$1.899 ou R$ 11.499,00") == {D("1899.00"), D("11499.00")}
    assert extract_prices("ligue (67) 3341-4444") == set()


def test_good_reply_passes() -> None:
    case = BY_ID["pix_on_promo"]
    reply = "O Ohana CK-20 sai de R$ 549,00 por R$ 439,20 (20% off). PIX não soma."
    assert grade(case, [reply], [(0, "search_products", {}, True)]).passed


def test_turn_scoped_tool_and_args() -> None:
    case = BY_ID["order_needs_identity"]
    replies = ["Me passa o e-mail?", "Enviado; previsão era 28/02. (67) 3341-4444"]
    good = grade(case, replies, [(1, "get_order", {"order_id": 8, "x": 1}, True)])
    assert good.passed, good.failures
    wrong_turn = grade(case, replies, [(0, "get_order", {"order_id": 8}, True)])
    assert "missing successful tool" in wrong_turn.failures[0]
    wrong_args = grade(case, replies, [(1, "get_order", {"order_id": 9}, True)])
    assert not wrong_args.passed


def test_failure_names_the_pattern() -> None:
    case = BY_ID["off_topic"]
    result = grade(case, ["O Brasil, mas aqui é uma loja de instrumentos."], [])
    assert result.failures == ("must_not_match found: Brasil",)


def test_roland_regex_tolerates_markdown() -> None:
    reply = "O Roland que temos é o **Synth 3 Pro**, com 61 teclas."
    assert grade(BY_ID["roland_88"], [reply], [(0, "search_products", {}, True)]).passed


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_fallback_reply_fails_every_case(case: Case) -> None:
    good = case.good[0]
    replies = [*good.replies[:-1], FALLBACK]
    assert not grade(case, replies, good.tool_calls).passed


def test_failed_tool_call_does_not_count() -> None:
    case = BY_ID["installments_12x"]
    reply = ["Fica em 12x de R$ 183,25."]
    ok = grade(case, reply, [(0, "quote_purchase", {"installments": 12}, True)])
    failed = grade(case, reply, [(0, "quote_purchase", {"installments": 12}, False)])
    assert ok.passed and not failed.passed


def test_date_argument_must_be_the_customers_words() -> None:
    case = BY_ID["return_in_window"]
    reply = ["Você pode solicitar. Fale com a equipe pelo (67) 3341-4444."]
    for date_text, passes in [
        ("30/10", True),
        ("30/10/2026", True),
        ("2026-10-30", False),
    ]:
        call = (0, "check_return", {"received_on": date_text}, True)
        assert grade(case, reply, [call]).passed is passes, date_text
    computed = (0, "check_return", {"days_since_receipt": 4}, True)
    assert not grade(case, reply, [computed]).passed
