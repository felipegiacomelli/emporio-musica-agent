import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import openai

from emporio.agent import FALLBACK, MAX_ROUNDS, Agent, to_markdown
from emporio.data import load_store
from emporio.tools import TOOL_SCHEMAS

STORE = load_store()
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=ZoneInfo("America/Campo_Grande"))


def call(name: str, args: dict[str, Any], call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call", name=name, arguments=json.dumps(args), call_id=call_id
    )


def message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        output=[SimpleNamespace(type="message", content=text)],
        output_text=text,
        model="fake-model",
    )


def calls(*items: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(output=list(items), output_text="", model="fake-model")


class FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.requests: list[dict[str, Any]] = []
        self.responses = self

    def create(self, **kw: Any) -> Any:
        self.requests.append({**kw, "input": list(kw["input"])})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def agent(script: list[Any]) -> tuple[Agent, FakeClient]:
    client = FakeClient(script)
    return Agent(client, STORE, "fake-model", "low", clock=lambda: NOW), client  # type: ignore[arg-type]


def outputs(request: dict[str, Any]) -> dict[str, str]:
    return {
        i["call_id"]: i["output"]
        for i in request["input"]
        if isinstance(i, dict) and i.get("type") == "function_call_output"
    }


def test_runs_all_parallel_calls_then_answers() -> None:
    a, client = agent(
        [
            calls(
                call("search_products", {"query": "Takamine GD20"}, "c1"),
                call("search_products", {"query": "Yamaha C40"}, "c2"),
            ),
            message("O GD20 custa R$ 2.199,00."),
        ]
    )
    turn = a.reply("Quanto custam o GD20 e o C40?")
    assert turn.reply == "O GD20 custa R$ 2.199,00." and not turn.fallback
    assert [c.name for c in turn.tool_calls] == ["search_products"] * 2
    assert set(outputs(client.requests[1])) == {"c1", "c2"}
    assert "R$ 2.199,00" in outputs(client.requests[1])["c1"]
    assert turn.model == "fake-model" and a.turns == [turn]


def test_history_carries_to_next_turn() -> None:
    a, client = agent([message("Oi!"), message("Claro.")])
    a.reply("Olá")
    a.reply("Pode ajudar?")
    users = [
        i["content"]
        for i in client.requests[1]["input"]
        if isinstance(i, dict) and i.get("role") == "user"
    ]
    assert users == ["Olá", "Pode ajudar?"]


def test_round_cap_returns_fallback() -> None:
    script: list[Any] = [
        calls(call("search_products", {"query": "x"}, f"c{i}"))
        for i in range(MAX_ROUNDS)
    ]
    a, client = agent(script)
    turn = a.reply("loop")
    assert turn.reply == FALLBACK and turn.fallback
    assert len(client.requests) == MAX_ROUNDS


def test_api_error_returns_fallback_and_history_stays_valid() -> None:
    error = openai.OpenAIError("connection reset")
    a, client = agent(
        [
            calls(call("search_products", {"query": "x"}, "c1")),
            error,
            message("Agora sim."),
        ]
    )
    first = a.reply("primeira")
    assert first.reply == FALLBACK and first.fallback
    second = a.reply("segunda")
    assert second.reply == "Agora sim."
    sent = client.requests[-1]["input"]
    # rolled back: no dangling function_call from the failed turn
    assert not any(getattr(i, "type", None) == "function_call" for i in sent)
    assert {"role": "assistant", "content": FALLBACK} in sent


def test_empty_answer_returns_fallback() -> None:
    a, _ = agent([message("")])
    assert a.reply("oi").fallback


def test_bad_tool_args_go_back_to_model() -> None:
    bad = SimpleNamespace(
        type="function_call", name="search_products", arguments="not json", call_id="c1"
    )
    a, client = agent([calls(bad), message("Desculpe.")])
    turn = a.reply("oi")
    assert "error" in json.loads(outputs(client.requests[1])["c1"])
    assert turn.reply == "Desculpe."


def test_clock_reaches_prompt_and_tools() -> None:
    args = {"order_id": 8, "email_or_phone": "67996547821"}
    a, client = agent([calls(call("get_order", args, "c1")), message("ok")])
    a.reply("pedido 8, tel 67996547821")
    assert "03/11/2026" in client.requests[0]["instructions"]
    assert json.loads(outputs(client.requests[1])["c1"])["delivery_overdue"] is True


def test_request_params() -> None:
    a, client = agent([message("ok")])
    a.reply("oi")
    kw = client.requests[0]
    assert kw["store"] is False and kw["tools"] is TOOL_SCHEMAS
    assert kw["include"] == ["reasoning.encrypted_content"]
    assert kw["reasoning"] == {"effort": "low"} and kw["model"] == "fake-model"


def test_to_markdown() -> None:
    a, _ = agent(
        [
            calls(call("search_products", {"query": "Ohana"}, "c1")),
            message("Temos o Ohana."),
        ]
    )
    a.reply("Tem Ohana?")
    md = to_markdown(a.turns, "Exemplo")
    assert md.startswith("# Exemplo")
    assert "### Cliente" in md and "### Agente" in md
    assert "search_products" in md and "Temos o Ohana." in md
