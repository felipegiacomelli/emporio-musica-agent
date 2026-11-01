from typing import Any

import pytest

from emporio.__main__ import main
from emporio.agent import Turn


class StubAgent:
    def __init__(self) -> None:
        self.turns: list[Turn] = []
        self.calls: list[str] = []

    def reply(self, user_text: str) -> Turn:
        self.calls.append(user_text)
        turn = Turn(user_text, "Olá, cliente!", (), False, "stub")
        self.turns.append(turn)
        return turn


def inputs(*lines: str) -> Any:
    it = iter(lines)

    def fn(_prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return fn


def test_greeting_reply_and_blank_line(capsys: pytest.CaptureFixture[str]) -> None:
    agent = StubAgent()
    code = main([], agent=agent, input_fn=inputs("  ", "oi"))
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("Empório da Música — assistente virtual.") == 1
    assert "Empório: Olá, cliente!" in out
    assert agent.calls == ["oi"]
    assert "Até mais! 🎸" in out


def test_keyboard_interrupt(capsys: pytest.CaptureFixture[str]) -> None:
    def fn(_prompt: str) -> str:
        raise KeyboardInterrupt

    assert main([], agent=StubAgent(), input_fn=fn) == 0
    assert "Até mais! 🎸" in capsys.readouterr().out


def test_transcript(tmp_path: Any) -> None:
    path = tmp_path / "t.md"
    main(
        ["--transcript", str(path)],
        agent=StubAgent(),
        input_fn=inputs("quero um violão"),
    )
    assert "quero um violão" in path.read_text(encoding="utf-8")


def test_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main([]) == 2
    err = capsys.readouterr().err
    assert err.strip() == (
        "OPENAI_API_KEY não configurada. "
        "Copie .env.example para .env e preencha a chave."
    )
