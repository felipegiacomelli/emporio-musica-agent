"""Deterministic graders for the frozen eval cases.

A case passes only when every check passes. Every case has at least one
positive check, so an empty or evasive reply fails.
"""

import re
import tomllib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from attrs import frozen

type Call = tuple[int, str, dict[str, Any]]  # (turn, tool name, arguments)

CENT = Decimal("0.01")
_FLAGS = re.IGNORECASE | re.DOTALL
_MONEY = re.compile(
    r"(?<![\d.,])(R\$\s*)?"
    r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+,\d{2}|\d+\.\d{2}(?!\d)|\d+)"
    r"(?![\d])"
)


def extract_prices(text: str) -> set[Decimal]:
    """Money amounts in a reply, in pt-BR (2.199,00) or dot-decimal (439.20) form.

    Amounts with a decimal part or thousands dots always count; a bare integer
    counts only after "R$" (so dates, phones, "12x" and "20%" are ignored).
    """
    found = set()
    for match in _MONEY.finditer(text):
        prefix, num = match.groups()
        if "," in num:
            value = num.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d+\.\d{2}", num):
            value = num
        elif "." in num:
            value = num.replace(".", "")
        elif prefix:
            value = num
        else:
            continue
        found.add(Decimal(value).quantize(CENT))
    return found


@frozen
class ExpectedTool:
    name: str
    args: dict[str, Any]
    turn: int | None


@frozen
class Fixture:
    replies: tuple[str, ...]
    tool_calls: tuple[Call, ...]


@frozen
class Case:
    id: str
    turns: tuple[str, ...]
    clock: str
    expect_tools: tuple[ExpectedTool, ...]
    forbid_tools: tuple[str, ...]
    must_match: tuple[str, ...]
    must_not_match: tuple[str, ...]
    must_not_match_turns: dict[int, tuple[str, ...]]
    must_prices: tuple[Decimal, ...]
    must_not_prices: tuple[Decimal, ...]
    bad: tuple[Fixture, ...]
    good: tuple[Fixture, ...]


@frozen
class Result:
    case_id: str
    passed: bool
    failures: tuple[str, ...]


def _calls(raw: list[dict[str, Any]]) -> tuple[Call, ...]:
    return tuple((c["turn"], c["name"], c.get("args", {})) for c in raw)


def load_cases(path: Path) -> tuple[int, list[Case]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cases = []
    for c in data["case"]:
        case = Case(
            id=c["id"],
            turns=tuple(c["turns"]),
            clock=c.get("clock", data["clock"]),
            expect_tools=tuple(
                ExpectedTool(t["name"], t.get("args", {}), t.get("turn"))
                for t in c.get("expect_tools", [])
            ),
            forbid_tools=tuple(c.get("forbid_tools", [])),
            must_match=tuple(c.get("must_match", [])),
            must_not_match=tuple(c.get("must_not_match", [])),
            must_not_match_turns={
                int(k): tuple(v) for k, v in c.get("must_not_match_turns", {}).items()
            },
            must_prices=tuple(Decimal(p) for p in c.get("must_prices", [])),
            must_not_prices=tuple(Decimal(p) for p in c.get("must_not_prices", [])),
            bad=tuple(
                Fixture(tuple(b["replies"]), _calls(b.get("tool_calls", [])))
                for b in c["bad"]
            ),
            good=tuple(
                Fixture(tuple(g["replies"]), _calls(g.get("tool_calls", [])))
                for g in c.get("good", [])
            ),
        )
        if not (case.must_match or case.must_prices or case.expect_tools):
            raise ValueError(f"{case.id}: needs at least one positive check")
        if not case.bad or not case.good:
            raise ValueError(f"{case.id}: needs a good and a bad fixture")
        cases.append(case)
    return data["version"], cases


def grade(case: Case, replies: Sequence[str], tool_calls: Sequence[Call]) -> Result:
    failures: list[str] = []
    last = replies[-1] if replies else ""
    if not last.strip():
        failures.append("empty reply")

    for exp in case.expect_tools:
        if not any(
            name == exp.name
            and (exp.turn is None or turn == exp.turn)
            and all(args.get(k) == v for k, v in exp.args.items())
            for turn, name, args in tool_calls
        ):
            where = "any turn" if exp.turn is None else f"turn {exp.turn}"
            failures.append(f"missing tool {exp.name}{exp.args} in {where}")
    for name in case.forbid_tools:
        if any(n == name for _, n, _ in tool_calls):
            failures.append(f"forbidden tool called: {name}")

    for pattern in case.must_match:
        if not re.search(pattern, last, _FLAGS):
            failures.append(f"must_match not found: {pattern}")
    for pattern in case.must_not_match:
        if re.search(pattern, last, _FLAGS):
            failures.append(f"must_not_match found: {pattern}")
    for turn, patterns in case.must_not_match_turns.items():
        text = replies[turn] if turn < len(replies) else ""
        for pattern in patterns:
            if re.search(pattern, text, _FLAGS):
                failures.append(f"turn {turn} must_not_match found: {pattern}")

    prices = extract_prices(last)
    for price in case.must_prices:
        if price.quantize(CENT) not in prices:
            failures.append(f"price missing: {price}")
    for price in case.must_not_prices:
        if price.quantize(CENT) in prices:
            failures.append(f"forbidden price: {price}")

    return Result(case.id, not failures, tuple(failures))
